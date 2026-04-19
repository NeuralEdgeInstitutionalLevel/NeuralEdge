"""
Notification service for Telegram signal delivery and admin alerts.
"""
import logging
from typing import Optional
from config import settings

logger = logging.getLogger("neuraledge.notifications")


class NotificationService:
    """Send notifications via Telegram."""

    async def send_signal_telegram(
        self,
        chat_id: str,
        pair: str,
        direction: str,
        confidence: float,
        entry_price: float,
        sl_price: Optional[float] = None,
    ):
        """Send trading signal to user's Telegram."""
        if not settings.TELEGRAM_BOT_TOKEN or not chat_id:
            return

        emoji = "🟢" if direction == "long" else "🔴"
        sl_text = f"\nSL: ${sl_price:,.2f}" if sl_price else ""

        message = (
            f"{emoji} <b>NeuralEdge Signal</b>\n\n"
            f"<b>{pair}</b> - {direction.upper()}\n"
            f"Entry: ${entry_price:,.2f}{sl_text}\n"
            f"Confidence: {confidence:.1%}\n\n"
            f"<i>Auto-execution available on Pro/Elite plans</i>"
        )

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=10.0,
                )
        except Exception as e:
            logger.error(f"Telegram send failed for {chat_id}: {e}")

    async def send_admin_alert(self, message: str):
        """Send alert to admin Telegram."""
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_ADMIN_CHAT_ID:
            return

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": settings.TELEGRAM_ADMIN_CHAT_ID,
                        "text": f"🔔 <b>Admin Alert</b>\n\n{message}",
                        "parse_mode": "HTML",
                    },
                    timeout=10.0,
                )
        except Exception as e:
            logger.error(f"Admin alert failed: {e}")


notification_service = NotificationService()
