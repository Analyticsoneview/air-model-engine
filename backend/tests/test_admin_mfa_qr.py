from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts.mfa_setup import build_totp_uri, new_totp_secret, write_totp_qr


def test_new_totp_secret_is_160_bit_base32():
    import base64

    secret = new_totp_secret()
    assert len(secret) == 32
    assert len(base64.b32decode(secret)) == 20


def test_totp_uri_contains_standard_authenticator_parameters():
    secret = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    uri = build_totp_uri("Admin+air@example.com", secret)
    parsed = urlparse(uri)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "otpauth"
    assert parsed.netloc == "totp"
    assert params["secret"] == [secret]
    assert params["issuer"] == ["AIR"]
    assert params["algorithm"] == ["SHA1"]
    assert params["digits"] == ["6"]
    assert params["period"] == ["30"]


def test_qr_is_written_as_local_svg_without_plaintext_secret(tmp_path):
    secret = new_totp_secret()
    uri = build_totp_uri("root@example.com", secret)
    path = write_totp_qr(uri, tmp_path / "setup.svg")
    content = path.read_text(encoding="utf-8")
    assert path.exists()
    assert "<svg" in content
    assert secret not in content
    assert uri not in content
