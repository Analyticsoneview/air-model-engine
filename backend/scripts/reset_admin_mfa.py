"""Secure local Super Admin TOTP rotation with QR enrollment.

Run inside the AIR API container:
  python -m scripts.reset_admin_mfa

Requires the administrator's current password and verification of the newly
scanned TOTP code. Existing sessions are revoked after a successful rotation.
"""
from getpass import getpass

from app.admin_auth import get_admin_auth_store, verify_totp
from scripts.mfa_setup import build_totp_uri, new_totp_secret, qr_output_path, write_totp_qr


def main() -> None:
    email = input("Administrator email: ").strip()
    password = getpass("Current administrator password: ")
    store = get_admin_auth_store()
    qr_path = None
    try:
        secret = new_totp_secret()
        uri = build_totp_uri(email, secret)
        qr_path = write_totp_qr(uri, qr_output_path())
        print("\nAIR MFA rotation")
        print("1. In a second PowerShell window, run:")
        print(r"   docker compose -f compose.local.yml cp air-api:/var/lib/air/air-admin-mfa-setup.svg .\AIR-Admin-MFA-Setup.svg")
        print("2. Open AIR-Admin-MFA-Setup.svg on this PC and scan it with your authenticator app.")
        code = input("Enter the new six-digit authenticator code: ").strip()
        if not verify_totp(secret, code):
            raise SystemExit("TOTP verification failed. Existing MFA was not changed.")
        store.rotate_mfa_secret(email, password, secret)
        print("\nMFA secret rotated and verified. Existing administrator sessions were revoked.")
        print("Delete the copied QR file from the Windows host:")
        print(r"   Remove-Item .\AIR-Admin-MFA-Setup.svg")
    except (ValueError, RuntimeError, PermissionError) as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        if qr_path is not None:
            qr_path.unlink(missing_ok=True)
        store.close()


if __name__ == "__main__":
    main()
