"""
Signal Emitter Bridge.
Thin adapter imported into Trading_loop_v2.py to emit signals to the SaaS backend.
Fire-and-forget: never blocks the main trading loop.

Usage in Trading_loop_v2.py:
    from saas_platform.backend.bridge.signal_emitter import emit_signal

    # After signal is generated:
    emit_signal(
        pair="BTC/USDT",
        direction="long",
        confidence=0.73,
        entry_price=87450.0,
        sl_price=86100.0,
        alpha_prob=0.73,
        lgbm_prob=0.68,
        meta_prob=0.71,
        uncertainty=0.15,
        regime="trending",
        magnitude=0.012,
    )
"""
import os
import logging
import threading
from typing import Optional

logger = logging.getLogger("neuraledge.signal_emitter")

BACKEND_URL = os.getenv("NEURALEDGE_BACKEND_URL", "http://localhost:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


def emit_signal(
    pair: str,
    direction: str,
    confidence: float,
    entry_price: float,
    sl_price: Optional[float] = None,
    tp_price: Optional[float] = None,
    alpha_prob: Optional[float] = None,
    lgbm_prob: Optional[float] = None,
    meta_prob: Optional[float] = None,
    uncertainty: Optional[float] = None,
    regime: Optional[str] = None,
    magnitude: Optional[float] = None,
    subsystem_data: Optional[dict] = None,
):
    """
    Fire-and-forget signal emission to the SaaS backend.
    Runs in a background thread to never block the trading loop.
    """
    def _send():
        try:
            import httpx
            payload = {
                "pair": pair,
                "direction": direction,
                "confidence": confidence,
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "alpha_prob": alpha_prob,
                "lgbm_prob": lgbm_prob,
                "meta_prob": meta_prob,
                "uncertainty": uncertainty,
                "regime": regime,
                "magnitude": magnitude,
                "subsystem_data": subsystem_data or {},
            }
            resp = httpx.post(
                f"{BACKEND_URL}/api/internal/signal",
                json=payload,
                headers={"X-Internal-Key": INTERNAL_API_KEY},
                timeout=5.0,
            )
            if resp.status_code == 200:
                logger.debug(f"Signal emitted: {pair} {direction} conf={confidence:.3f}")
            else:
                logger.warning(f"Signal emit failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.debug(f"Signal emit error (non-critical): {e}")

    # Fire and forget in background thread
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def emit_heartbeat():
    """Send heartbeat to backend (called every cycle)."""
    def _send():
        try:
            import httpx
            httpx.post(
                f"{BACKEND_URL}/api/internal/heartbeat",
                headers={"X-Internal-Key": INTERNAL_API_KEY},
                timeout=3.0,
            )
        except Exception:
            pass

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def emit_trade_result(
    pair: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    pnl_usd: float,
    pnl_pct: float,
    exit_reason: str,
):
    """Emit trade result to backend for tracking."""
    def _send():
        try:
            import httpx
            httpx.post(
                f"{BACKEND_URL}/api/internal/trade-result",
                json={
                    "pair": pair,
                    "direction": direction,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_usd": pnl_usd,
                    "pnl_pct": pnl_pct,
                    "exit_reason": exit_reason,
                },
                headers={"X-Internal-Key": INTERNAL_API_KEY},
                timeout=5.0,
            )
        except Exception:
            pass

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
