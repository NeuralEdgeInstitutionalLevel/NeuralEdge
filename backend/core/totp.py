"""
NeuralEdge AI - Two-Factor Authentication (TOTP)

Time-based One-Time Password (RFC 6238) using PyOTP.
Compatible with Google Authenticator, Authy, 1Password, etc.

Usage:
    from core.totp import generate_totp_secret, verify_totp, get_provisioning_uri

    secret = generate_totp_secret()           # Store in user record
    uri = get_provisioning_uri(secret, email)  # Generate QR code from this
    is_valid = verify_totp(secret, "123456")   # Verify 6-digit code
"""
import pyotp
import qrcode
import io
import base64


def generate_totp_secret() -> str:
    """Generate a new TOTP secret (base32 encoded, 32 chars)."""
    return pyotp.random_base32()


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    """Verify a 6-digit TOTP code.

    Args:
        secret: The user's TOTP secret (base32)
        code: The 6-digit code to verify
        window: Number of 30-second windows to check (1 = +/- 30 seconds)

    Returns:
        True if the code is valid within the time window.
    """
    if not secret or not code:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=window)


def get_provisioning_uri(secret: str, email: str) -> str:
    """Get the otpauth:// URI for QR code generation.

    Users scan this with Google Authenticator / Authy.
    """
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name="NeuralEdge AI")


def generate_qr_base64(secret: str, email: str) -> str:
    """Generate a QR code as base64 PNG for embedding in HTML/API response.

    Returns:
        Base64-encoded PNG image string (data:image/png;base64,...)
    """
    uri = get_provisioning_uri(secret, email)
    qr = qrcode.QRCode(version=1, box_size=6, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"
