#!/usr/bin/env python3
"""Check pinned broker SDKs against PyPI and update only vendor requirement pins.

This script never installs packages or changes production dependencies. It edits
requirements files on an automation branch; CI must validate the resulting PR.
"""
from __future__ import annotations
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BROKER_DIR = ROOT / "dependencies" / "brokers"
REPORT = ROOT / "broker-sdk-update-report.json"
ALLOWLIST = {
    "zerodha.txt": {"kiteconnect"},
    "upstox.txt": {"upstox-python-sdk"},
    "fyers.txt": {"fyers-apiv3"},
    "angel-one.txt": {"smartapi-python"},
}
PIN = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^;]+)(?P<tail>.*)$")

def pypi_latest(package: str) -> str:
    request = urllib.request.Request(
        f"https://pypi.org/pypi/{package}/json",
        headers={"User-Agent": "AIR-Broker-SDK-Monitor/1.0"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        version = json.load(response).get("info", {}).get("version")
    if not version:
        raise RuntimeError(f"PyPI did not return a stable current version for {package}")
    return str(version)

def main() -> int:
    changed, checked, errors = [], [], []
    for filename, allowed in ALLOWLIST.items():
        path = BROKER_DIR / filename
        lines = path.read_text(encoding="utf-8").splitlines()
        output = []
        for line in lines:
            match = PIN.match(line.strip())
            if not match or match.group("name") not in allowed:
                output.append(line)
                continue
            package, current = match.group("name"), match.group("version")
            try:
                latest = pypi_latest(package)
                checked.append({"package": package, "current": current, "latest": latest})
                if latest != current:
                    output.append(f"{package}=={latest}{match.group('tail')}")
                    changed.append({
                        "package": package, "from": current, "to": latest,
                        "file": str(path.relative_to(ROOT)),
                    })
                else:
                    output.append(line)
            except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError) as exc:
                errors.append(f"{package}: {exc}")
                output.append(line)
        path.write_text("\n".join(output) + "\n", encoding="utf-8")
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "checked": checked,
        "updates": changed,
        "errors": errors,
        "policy": "Updates are proposed in a PR; they are not deployed automatically.",
    }
    # Do not change a tracked file on no-op days; otherwise the bot would open
    # an empty dependency PR every morning.
    if changed:
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
