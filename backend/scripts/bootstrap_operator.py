"""Create the first AIR operator locally before exposing the API.

Run from the backend directory after installing requirements:
    python scripts/bootstrap_operator.py
The password is entered interactively and is never echoed or stored in shell history.
"""
import os
from getpass import getpass
from uuid import uuid4

from app.auth_store import AuthStore
from app.security import hash_password


def main() -> None:
    db_path = os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3")
    email = input("AIR operator email: ").strip()
    password = getpass("Password (minimum 12 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")

    customer_id = str(uuid4())
    store = AuthStore(db_path)
    try:
        store.create_customer(customer_id, email, hash_password(password))
    except Exception as exc:
        raise SystemExit(f"Could not create operator (email may already exist): {exc}") from exc
    finally:
        store.close()

    print("\nAIR operator created.")
    print(f"Customer UUID: {customer_id}")
    print("Set AIR_OPERATOR_CUSTOMER_IDS to this UUID in the API service environment.")
    print("Keep the UUID private; do not add it to source control.")


if __name__ == "__main__":
    main()
