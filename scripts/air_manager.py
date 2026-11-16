#!/usr/bin/env python3
"""Cross-platform AIR Deployment Manager.

This manager validates profiles and routes local installation/upgrade through the
same AIRSTART readiness gate on Windows, Linux and macOS. AWS actions are
explicitly reported as deferred until an authorized AWS environment exists.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.deployment_profiles import (  # noqa: E402
    DeploymentProfileError,
    SUPPORTED_PROFILES,
    load_profile,
)

ACTIONS = ("validate", "doctor", "install", "upgrade", "status", "diagnose", "package")
REQUIRED_FILES = (
    "AIRDEPLOY.sh", "AIRDEPLOY.ps1", "AIRSTART.sh", "AIRSTART.ps1",
    "compose.local.yml", "docker-stack.yml", "backend/Dockerfile",
    "deploy/pwa.Dockerfile", "deploy/deploy-swarm.sh", "deploy/rabbitmq.conf",
    "docs/AIR_INSTALLATION_READINESS.md",
)


class ManagerError(RuntimeError):
    pass


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def validate(profile_id: str) -> dict[str, Any]:
    profile = load_profile(profile_id, require_cloud_env=False)
    missing = [name for name in REQUIRED_FILES if not (ROOT / name).is_file()]
    if missing:
        raise ManagerError("Required deployment inputs are missing: " + ", ".join(missing))
    provider = profile["deployment"]["provider"]
    if provider == "aws":
        terraform_files = ("versions.tf", "variables.tf", "network.tf", "ecs.tf", "data.tf", "security.tf", "outputs.tf")
        missing_tf = [
            f"deploy/aws/terraform/{name}"
            for name in terraform_files
            if not (ROOT / "deploy/aws/terraform" / name).is_file()
        ]
        if missing_tf:
            raise ManagerError("AWS Terraform source is incomplete: " + ", ".join(missing_tf))
    return {
        "status": "VALID",
        "profile_id": profile_id,
        "provider": provider,
        "tenancy": profile["deployment"]["tenancy"],
        "orchestrator": profile["deployment"]["orchestrator"],
        "services": sorted(profile["services"]),
        "deployment_status": "READY_FOR_LOCAL_PREFLIGHT" if provider == "on_prem" else "DEFERRED_UNTIL_AWS_ENVIRONMENT",
    }


def run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManagerError(f"Could not run {command[0]}: {exc}") from exc


def docker_doctor() -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        raise ManagerError("Docker CLI is not installed. Install Docker Desktop or Docker Engine first.")
    version = run([docker, "version", "--format", "{{.Client.Version}}"])
    if version.returncode:
        raise ManagerError(version.stderr.strip() or "Docker client version check failed.")
    compose = run([docker, "compose", "version", "--short"])
    if compose.returncode:
        raise ManagerError(compose.stderr.strip() or "Docker Compose v2 is unavailable.")
    daemon = run([docker, "info", "--format", "{{.ServerVersion}}"])
    if daemon.returncode:
        raise ManagerError("Docker daemon is not running. Start Docker Desktop/Engine and retry.")
    disk = shutil.disk_usage(ROOT)
    free_gb = round(disk.free / (1024 ** 3), 2)
    return {
        "docker_client": version.stdout.strip(),
        "docker_server": daemon.stdout.strip(),
        "docker_compose": compose.stdout.strip(),
        "free_disk_gb": free_gb,
        "disk_status": "OK" if free_gb >= 5 else "LOW",
    }


def probe(url: str, timeout: float = 3.0) -> dict[str, Any]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "AIR-Deployment-Manager/1"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2048).decode("utf-8", "replace")
            return {"url": url, "status": response.status, "healthy": response.status == 200, "body": body}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"url": url, "status": None, "healthy": False, "error": type(exc).__name__}


def local_status() -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        raise ManagerError("Docker CLI is not installed.")
    services = run([docker, "compose", "-f", "compose.local.yml", "ps", "--format", "json"])
    return {
        "profile": "onprem-single",
        "compose_exit_code": services.returncode,
        "services": services.stdout.strip().splitlines() if services.stdout.strip() else [],
        "service_error": services.stderr.strip() if services.returncode else None,
        "api_health": probe("http://127.0.0.1:8000/health"),
        "installation_readiness": probe("http://127.0.0.1:8000/ready", timeout=5),
        "pwa_health": probe("http://127.0.0.1:8080/health"),
    }


def invoke_installer(*, upgrade: bool) -> int:
    environment = os.environ.copy()
    if upgrade:
        environment["AIR_START_SKIP_OPEN"] = "true"
        environment["AIR_START_SKIP_PROFILE"] = "true"
        environment["AIR_START_PULL_BASE_IMAGES"] = "true"
    if os.name == "nt":
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            raise ManagerError("PowerShell is required to run the Windows AIR installer.")
        command = [
            powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(ROOT / "AIRSTART.ps1"),
        ]
    else:
        bash = shutil.which("bash")
        if not bash:
            raise ManagerError("Bash is required to run the AIR on-prem installer.")
        command = [bash, str(ROOT / "AIRSTART.sh")]
    try:
        return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode
    except OSError as exc:
        raise ManagerError(f"Could not start AIR installer: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AIR Deployment Manager — one product, profile-driven installation and release tooling."
    )
    parser.add_argument("--profile", choices=sorted(SUPPORTED_PROFILES), default="onprem-single")
    parser.add_argument("--version", default=os.getenv("AIR_RELEASE_VERSION", "dev"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ACTIONS:
        sub.add_parser(action)
    args = parser.parse_args()

    try:
        profile = validate(args.profile)
        provider = profile["provider"]

        if args.action == "validate":
            emit(profile)
            return 0

        if args.action == "package":
            script = ROOT / "scripts/release/build_release.py"
            command = [
                sys.executable, str(script), "--version", args.version,
                "--output-dir", str(args.output_dir),
            ]
            result = run(command, timeout=900)
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            return result.returncode

        if provider == "aws":
            emit({
                "status": "DEFERRED",
                "profile_id": args.profile,
                "message": "AWS profile and Terraform source are valid. No AWS account, credentials, remote state or deployment approval is configured; no AWS resources were created.",
                "next_step": "When an AWS environment is authorized, configure remote state, region, role, certificate and budget, then run the separately approved AWS deployment procedure.",
            })
            return 0

        if args.action == "doctor":
            emit({"status": "READY" if docker_doctor()["disk_status"] == "OK" else "WARNING", **docker_doctor()})
            return 0

        if args.action == "status":
            status = local_status()
            emit(status)
            return 0 if status["api_health"]["healthy"] and status["pwa_health"]["healthy"] else 2

        if args.action == "diagnose":
            report = {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "profile": profile,
                "host": docker_doctor(),
                "runtime": local_status(),
                "notes": [
                    "This report does not contain secret file contents or container environment values.",
                    "Use docker compose logs --tail 100 to inspect service logs locally before sharing them.",
                    "HTTP /health is not full installation readiness; check /ready separately.",
                ],
            }
            directory = ROOT / ".air-diagnostics"
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination = directory / f"air-diagnostics-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
            destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            try:
                destination.chmod(0o600)
            except OSError:
                pass
            emit({"status": "CREATED", "report": str(destination), "runtime": report["runtime"]})
            return 0

        if args.action == "install":
            docker_doctor()
            return invoke_installer(upgrade=False)

        if args.action == "upgrade":
            docker_doctor()
            return invoke_installer(upgrade=True)

        raise ManagerError(f"Unsupported action: {args.action}")
    except (DeploymentProfileError, ManagerError, OSError, ValueError) as exc:
        emit({"status": "ERROR", "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
