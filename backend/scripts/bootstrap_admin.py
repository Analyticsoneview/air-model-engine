"""One-time interactive bootstrap for the first AIR Super Admin.

Run from backend: python -m scripts.bootstrap_admin
AIR_ADMIN_MFA_KEY_FILE must point to a Fernet key file created offline.
"""
from getpass import getpass
from urllib.parse import quote
from app.admin_auth import AdminAuthStore

def main():
    email=input("Super Admin email: ").strip()
    password=getpass("Password (minimum 12 characters): ")
    confirm=getpass("Confirm password: ")
    if password != confirm: raise SystemExit("Passwords do not match")
    store=AdminAuthStore()
    try:
        admin_id,secret=store.bootstrap(email,password)
    except (ValueError,RuntimeError) as exc:
        raise SystemExit(str(exc))
    finally:
        store.close()
    issuer="AIR"
    uri=f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    print("\nSuper Admin created. Add this TOTP URI to an authenticator app:")
    print(uri)
    print("\nStore the secret securely. It will not be displayed again.")
    print(f"Admin ID: {admin_id}")

if __name__ == "__main__": main()
