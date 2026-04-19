"""
NeuralEdge AI - WebSocket Routes

WebSocket /dashboard  -- real-time position updates, signals, equity

Authentication via ``token`` query parameter.
Subscribes to Redis pub/sub channels for live data push.

Channels:
  - neuraledge:signals        -> new signal generated
  - neuraledge:positions:{uid} -> position update for specific user
  - neuraledge:trades:{uid}   -> trade opened/closed for specific user
  - neuraledge:equity:{uid}   -> equity snapshot update
  - neuraledge:heartbeat      -> bot heartbeat (all users)
"""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from config import settings
from core.security import verify_token

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------
class ConnectionManager:
    """Manages active WebSocket connections per user."""

    def __init__(self) -> None:
        # user_id -> set of WebSocket connections
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
            self._connections[user_id].add(websocket)
        logger.info("WebSocket connected: user=%s total=%d", user_id, self.total_connections)

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].discard(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]
        logger.info("WebSocket disconnected: user=%s total=%d", user_id, self.total_connections)

    async def send_to_user(self, user_id: str, message: dict) -> None:
        """Send a JSON message to all connections for a specific user."""
        async with self._lock:
            connections = self._connections.get(user_id, set()).copy()

        disconnected = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)

        # Clean up broken connections
        if disconnected:
            async with self._lock:
                if user_id in self._connections:
                    for ws in disconnected:
                        self._connections[user_id].discard(ws)
                    if not self._connections[user_id]:
                        del self._connections[user_id]

    async def broadcast(self, message: dict) -> None:
        """Send a JSON message to all connected users."""
        async with self._lock:
            all_connections = [
                (uid, ws)
                for uid, conns in self._connections.items()
                for ws in conns
            ]

        for uid, ws in all_connections:
            try:
                await ws.send_json(message)
            except Exception:
                pass  # Cleanup happens in per-user send path

    @property
    def total_connections(self) -> int:
        return sum(len(conns) for conns in self._connections.values())

    @property
    def connected_users(self) -> list[str]:
        return list(self._connections.keys())


# Global connection manager
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------
def _authenticate_ws(token: str | None) -> str | None:
    """Validate a JWT token and return the user_id string, or None."""
    if not token:
        return None

    try:
        from jose import JWTError

        payload = verify_token(token)
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if user_id is None:
            return None
        # Validate UUID format
        uuid.UUID(user_id)
        return user_id
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Redis subscriber task
# ---------------------------------------------------------------------------
async def _redis_subscriber(user_id: str, websocket: WebSocket) -> None:
    """Subscribe to Redis pub/sub channels and forward messages to the WebSocket.

    Runs as a background task for each connected user.
    """
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )

    channels = [
        "neuraledge:signals",
        f"neuraledge:positions:{user_id}",
        f"neuraledge:trades:{user_id}",
        f"neuraledge:equity:{user_id}",
        "neuraledge:heartbeat",
    ]

    pubsub = redis_client.pubsub()
    try:
        await pubsub.subscribe(*channels)
        logger.info("Redis subscriber started for user=%s channels=%d", user_id, len(channels))

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            channel = message["channel"]
            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                data = {"raw": message["data"]}

            # Determine event type from channel name
            if "signals" in channel:
                event_type = "signal"
            elif "positions" in channel:
                event_type = "position_update"
            elif "trades" in channel:
                event_type = "trade_update"
            elif "equity" in channel:
                event_type = "equity_update"
            elif "heartbeat" in channel:
                event_type = "heartbeat"
            else:
                event_type = "unknown"

            ws_message = {
                "type": event_type,
                "channel": channel,
                "data": data,
            }

            try:
                await websocket.send_json(ws_message)
            except Exception:
                break  # WebSocket closed

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Redis subscriber error for user=%s: %s", user_id, exc)
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.close()
        await redis_client.close()
        logger.info("Redis subscriber stopped for user=%s", user_id)


# ---------------------------------------------------------------------------
# WebSocket /dashboard
# ---------------------------------------------------------------------------
@router.websocket("/dashboard")
async def dashboard_websocket(
    websocket: WebSocket,
    token: str | None = Query(None),
):
    """Real-time dashboard WebSocket endpoint.

    Connect with: ws://host/api/ws/dashboard?token=<access_token>

    After connection, the server:
    1. Subscribes to Redis pub/sub channels for the authenticated user
    2. Forwards all channel messages as JSON events
    3. Accepts client pings and responds with pongs

    Message format (server -> client):
    {
        "type": "signal" | "position_update" | "trade_update" | "equity_update" | "heartbeat",
        "channel": "neuraledge:signals",
        "data": { ... }
    }

    Client can send:
    {
        "type": "ping"
    }
    Server responds:
    {
        "type": "pong",
        "connections": <total_active_connections>
    }
    """
    # Authenticate
    user_id = _authenticate_ws(token)
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or missing token")
        return

    # Check if user tier allows dashboard
    from sqlalchemy import select as sa_select
    from db.session import async_session_factory
    from db.models.user import User

    async with async_session_factory() as db:
        result = await db.execute(
            sa_select(User).where(User.id == uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()

    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="User not found")
        return

    tier_limits = settings.TIER_LIMITS.get(user.tier, settings.TIER_LIMITS["free"])
    if not tier_limits.get("dashboard", False) and user.role != "admin":
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=f"Dashboard not available on {user.tier} tier",
        )
        return

    # Accept connection
    await manager.connect(user_id, websocket)

    # Start Redis subscriber as background task
    subscriber_task = asyncio.create_task(_redis_subscriber(user_id, websocket))

    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "data": {
                "user_id": user_id,
                "tier": user.tier,
                "channels": [
                    "neuraledge:signals",
                    f"neuraledge:positions:{user_id}",
                    f"neuraledge:trades:{user_id}",
                    f"neuraledge:equity:{user_id}",
                    "neuraledge:heartbeat",
                ],
            },
        })

        # Listen for client messages (ping/pong, etc.)
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=60.0,  # Client must send at least one message per minute
                )
            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue

            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "connections": manager.total_connections,
                })
            elif msg_type == "subscribe":
                # Future: allow dynamic channel subscription
                await websocket.send_json({
                    "type": "info",
                    "data": {"message": "Dynamic subscription not yet supported"},
                })
            else:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"Unknown message type: {msg_type}"},
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: user=%s", user_id)
    except Exception as exc:
        logger.error("WebSocket error for user=%s: %s", user_id, exc)
    finally:
        subscriber_task.cancel()
        try:
            await subscriber_task
        except asyncio.CancelledError:
            pass
        await manager.disconnect(user_id, websocket)
