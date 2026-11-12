"""One-time interactive Super Admin bootstrap with local QR-based TOTP enrollment.

Run inside the AIR API container:
  python -m scripts.bootstrap_admin

The QR is temporarily written to the AIR data volume. Copy it to the Windows host,
scan it, enter the six-digit code, and the container-side QR is then deleted.
"""
from getpass import getpass

from app.admin_auth import get_admin_auth_store, verify_totp
from scripts.mfa_setup import build_totp_uri, new_totp_secret, qr_output_path, write_totp_qr


def main() -> None:
    email = input("Super Admin email: ").strip()
    password = getpass("Password (minimum 12 characters): ")
    confirm = getpass("Confirm password: ")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters")
    if password != confirm:
        raise SystemExit("Passwords do not match")

    store = get_admin_auth_store()
    qr_path = None
    try:
        secret = new_totp_secret()
        uri = build_totp_uri(email, secret)
        qr_path = write_totp_qr(uri, qr_output_path())
        print("\nAIR Super Admin authenticator enrollment")
        print("1. In a second PowerShell window, run:")
        print(r"   docker compose -f compose.local.yml cp air-api:/var/lib/air/air-admin-mfa-setup.svg .\AIR-Admin-MFA-Setup.svg")
        print("2. Open AIR-Admin-MFA-Setup.svg on this PC and scan it with your authenticator app.")
        print("3. Enter the current six-digit code below to verify enrollment.")
        code = input("Authenticator code: ").strip()
        if not verify_totp(secret, code):
            raise SystemExit("TOTP verification failed. No Super Admin account was created.")
        admin_id, _ = store.bootstrap(email, password, secret)
        print("\nSuper Admin created and TOTP enrollment verified.")
        print(f"Admin ID: {admin_id}")
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
