"""Local TOTP provisioning helpers. Never log or print the provisioning URI."""
from __future__ import annotations

import base64
import secrets
from pathlib import Path
from urllib.parse import quote

import qrcode
from qrcode.image.svg import SvgPathImage


def new_totp_secret() -> str:
    """Return a 160-bit secret encoded as 32 unpadded Base32 characters."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def build_totp_uri(email: str, secret: str) -> str:
    if len(secret) != 32:
        raise ValueError("TOTP secret must be 32 Base32 characters (160 bits)")
    return (
        f"otpauth://totp/{quote('AIR')}:{quote(email.strip().lower())}"
        f"?secret={secret}&issuer=AIR&algorithm=SHA1&digits=6&period=30"
    )


def write_totp_qr(uri: str, output_path: str | Path) -> Path:
    """Write a self-contained SVG QR code locally; caller must remove it after use."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    image.save(str(path))
    return path


def qr_output_path() -> Path:
    return Path(__import__("os").environ.get(
        "AIR_ADMIN_MFA_QR_PATH", "/var/lib/air/air-admin-mfa-setup.svg"
    ))
