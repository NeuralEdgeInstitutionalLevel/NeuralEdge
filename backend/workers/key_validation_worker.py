"""
Periodic API key validation worker.
Tests exchange connectivity every 6 hours.
"""
import logging
from workers.celery_app import celery_app

logger = logging.getLogger("neuraledge.key_validation")


@celery_app.task(name="workers.key_validation_worker.validate_all_keys", queue="health")
def validate_all_keys():
    """Validate all stored API keys against exchanges."""
    import asyncio

    async def _validate():
        from sqlalchemy import select
        from db.session import async_session_factory
        from db.models.api_key import APIKey
        from core.encryption import decrypt
        from datetime import datetime, timezone

        async with async_session_factory() as db:
            result = await db.execute(select(APIKey).where(APIKey.is_valid == True))
            keys = result.scalars().all()

            validated = 0
            failed = 0

            for key_record in keys:
                try:
                    api_key = decrypt(key_record.api_key_enc, key_record.nonce)
                    api_secret = decrypt(key_record.api_secret_enc, key_record.nonce)
                    passphrase = None
                    if key_record.passphrase_enc:
                        passphrase = decrypt(key_record.passphrase_enc, key_record.nonce)

                    import ccxt.async_support as ccxt_async
                    exchange = ccxt_async.bitget({
                        "apiKey": api_key,
                        "secret": api_secret,
                        "password": passphrase,
                        "options": {"defaultType": "swap"},
                    })

                    # Just fetch balance to verify keys work
                    await exchange.fetch_balance()
                    await exchange.close()

                    key_record.last_validated = datetime.now(timezone.utc)
                    validated += 1

                except Exception as e:
                    logger.warning(f"API key {key_record.id} validation failed: {e}")
                    key_record.is_valid = False
                    failed += 1
                    if 'exchange' in locals():
                        try:
                            await exchange.close()
                        except Exception:
                            pass

            await db.commit()
            logger.info(f"Key validation: {validated} valid, {failed} failed")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_validate())
    finally:
        loop.close()
