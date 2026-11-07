"""Provision the AIR operator identity for admin-approved mobile access.

Run once on the server:
    python scripts/bootstrap_operator.py

The mobile number is the stable operator identity. The first device still
submits a request in the app; approve that request with the server-held
AIR_ADMIN_API_KEY. No OTP or phone ownership verification is performed.
"""
import re
from pathlib import Path

E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


def main() -> None:
    mobile = input("AIR operator mobile in international E.164 format (e.g. +919876543210): ").strip()
    if not E164.fullmatch(mobile):
        raise SystemExit("Invalid E.164 mobile number.")
    env_path = Path("/etc/air/air.env")
    if not env_path.exists():
        raise SystemExit(f"{env_path} is missing. Run the AIR installer first.")
    text = env_path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.startswith("AIR_OPERATOR_CUSTOMER_IDS=")]
    lines.append(f'AIR_OPERATOR_CUSTOMER_IDS="{mobile}"')
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_path.chmod(0o600)
    print("\nAIR operator identity configured.")
    print(f"Operator identity: {mobile}")
    print("Restart/redeploy the API after saving this configuration.")
    print("Submit an access request from the operator's device in the AIR app.")
    print("Approve that exact request using the protected admin API key.")
    print("After approval, the operator can manage access requests inside the AIR app.")
    print("IMPORTANT: mobile number is an identifier only; no OTP proves ownership.")


if __name__ == "__main__":
    main()
