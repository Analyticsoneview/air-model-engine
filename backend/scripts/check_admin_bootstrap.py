#!/usr/bin/env python3
"""Report whether an AIR administrator already exists; never prints account details."""
from __future__ import annotations
import json
from app.admin_auth import get_admin_auth_store

def main() -> int:
    store = get_admin_auth_store()
    try:
        admins = store.list_admins()
        print(json.dumps({"status": "EXISTS" if admins else "MISSING", "count": len(admins)}))
        return 0
    finally:
        store.close()

if __name__ == "__main__":
    raise SystemExit(main())
