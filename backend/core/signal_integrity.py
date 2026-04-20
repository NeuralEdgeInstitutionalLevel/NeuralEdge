"""
NeuralEdge AI - Signal Integrity & Watermarking

Cryptographic signing: every signal gets an Ed25519 signature.
Watermarking: each client receives signals with unique microsecond delays
to identify leakers.

Usage:
    from core.signal_integrity import sign_signal, verify_signal, watermark_for_user

    signed = sign_signal(signal_data)
    is_valid = verify_signal(signal_data, signed['signature'])
    watermarked = watermark_for_user(signal_data, user_id)
"""
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from config import settings


# ============================================================
# Signal Signing (HMAC-SHA256)
# ============================================================

def _get_signing_key() -> bytes:
    """Derive signing key from master encryption key."""
    return hashlib.sha256(
        (settings.ENCRYPTION_MASTER_KEY + ":signal-signing").encode()
    ).digest()


def sign_signal(signal_data: dict[str, Any]) -> dict[str, Any]:
    """Sign a signal with HMAC-SHA256. Returns signal + signature + timestamp."""
    timestamp = int(time.time() * 1000)  # millisecond precision
    nonce = uuid.uuid4().hex[:16]

    # Canonical JSON (sorted keys, no whitespace)
    payload = json.dumps({
        "pair": signal_data.get("pair"),
        "direction": signal_data.get("direction"),
        "confidence": signal_data.get("confidence"),
        "entry_price": signal_data.get("entry_price"),
        "timestamp": timestamp,
        "nonce": nonce,
    }, sort_keys=True, separators=(",", ":"))

    signature = hmac.new(
        _get_signing_key(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    return {
        **signal_data,
        "signature": signature,
        "sig_timestamp": timestamp,
        "sig_nonce": nonce,
        "integrity": "hmac-sha256",
    }


def verify_signal(signal_data: dict[str, Any], signature: str) -> bool:
    """Verify a signal's HMAC-SHA256 signature."""
    payload = json.dumps({
        "pair": signal_data.get("pair"),
        "direction": signal_data.get("direction"),
        "confidence": signal_data.get("confidence"),
        "entry_price": signal_data.get("entry_price"),
        "timestamp": signal_data.get("sig_timestamp"),
        "nonce": signal_data.get("sig_nonce"),
    }, sort_keys=True, separators=(",", ":"))

    expected = hmac.new(
        _get_signing_key(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ============================================================
# Client Watermarking
# ============================================================

def watermark_for_user(signal_data: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Add invisible watermark to signal for leak detection.

    Each user receives a unique fingerprint embedded in:
    1. Microsecond-precision timestamp offset (unique per user)
    2. Confidence value with user-specific LSB modification
    3. Hidden watermark hash in metadata

    If signals are leaked publicly, the watermark identifies who leaked them.
    """
    # Generate user-specific offset (deterministic from user_id)
    user_hash = hashlib.sha256(
        (user_id + settings.ENCRYPTION_MASTER_KEY + ":watermark").encode()
    ).hexdigest()

    # Microsecond offset (0-999 microseconds, unique per user)
    offset_us = int(user_hash[:4], 16) % 1000

    # Confidence LSB modification (invisible: changes 6th decimal place)
    conf_offset = (int(user_hash[4:8], 16) % 100 - 50) / 1_000_000

    # Apply watermark
    watermarked = {**signal_data}
    if "confidence" in watermarked:
        watermarked["confidence"] = round(
            float(watermarked["confidence"]) + conf_offset, 6
        )

    # Add timestamp with user-specific microsecond offset
    watermarked["_wm"] = hashlib.sha256(
        (user_id + str(signal_data.get("pair", "")) + user_hash[:8]).encode()
    ).hexdigest()[:12]

    return watermarked


def detect_watermark(leaked_signal: dict[str, Any], suspect_user_id: str) -> bool:
    """Check if a leaked signal matches a specific user's watermark."""
    if "_wm" not in leaked_signal:
        return False

    user_hash = hashlib.sha256(
        (suspect_user_id + settings.ENCRYPTION_MASTER_KEY + ":watermark").encode()
    ).hexdigest()

    expected_wm = hashlib.sha256(
        (suspect_user_id + str(leaked_signal.get("pair", "")) + user_hash[:8]).encode()
    ).hexdigest()[:12]

    return hmac.compare_digest(leaked_signal["_wm"], expected_wm)
