#!/usr/bin/env python3
"""Build and verify a secret-free, checksummed AIR release source bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = (
    "AIRDEPLOY.sh", "AIRDEPLOY.ps1", "AIRSTART.sh", "AIRSTART.ps1",
    "compose.local.yml", "docker-stack.yml", ".gitignore",
    "backend/Dockerfile", "backend/alembic.ini", "backend/requirements.txt",
    "backend/dependencies", "backend/app", "backend/config", "backend/migrations",
    "backend/scripts", "deploy", "mobile", "scripts/generate_local_secrets.py",
    "scripts/air_manager.py", "scripts/release/build_release.py",
    "docs/AIR_INSTALLATION_READINESS.md", "README.md",
)
EXCLUDED_PARTS = {
    ".git", ".air-secrets", ".venv", "venv", "node_modules", ".dart_tool",
    "build", "dist", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".gradle", "Pods", "DerivedData", "coverage", ".idea", ".vscode",
}
EXCLUDED_NAMES = {
    ".air-local.env", "key.properties", "terraform.tfstate",
    "terraform.tfstate.backup", "terraform.tfstate.lock.info",
}
EXCLUDED_SUFFIXES = {
    ".pyc", ".sqlite", ".sqlite3", ".db", ".log", ".pem", ".key",
    ".p12", ".pfx", ".jks", ".keystore", ".tfstate", ".tfvars",
}
SERVICE_INVENTORY = [
    {"name": "postgresql", "image": "postgres:16-alpine", "role": "persistent relational database", "persistent_volume": "postgres_data"},
    {"name": "redis", "image": "redis:7-alpine", "role": "cache and runtime coordination", "persistent_volume": "redis_data"},
    {"name": "rabbitmq", "image": "rabbitmq:4-management-alpine", "role": "durable workflow messaging", "persistent_volume": "rabbitmq_data"},
    {"name": "fastapi", "image": "air-model-engine-api:{release}", "dockerfile": "backend/Dockerfile", "role": "AIR API and Alembic migrations"},
    {"name": "workflow-worker", "image": "air-model-engine-api:{release}", "dockerfile": "backend/Dockerfile", "command": "python -m app.workflow_worker", "components": ["outbox", "scheduler", "executor", "operations-monitor"]},
    {"name": "pwa", "image": "air-model-engine-pwa:{release}", "dockerfile": "deploy/pwa.Dockerfile", "role": "Flutter web application served by Nginx"},
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def excluded(path: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return True
    if path.name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    if path.name.startswith(".env") or path.name.endswith((".bak", ".backup", ".dump")):
        return True
    return False


def source_files(root: Path) -> list[Path]:
    found: set[Path] = set()
    for item in INCLUDE:
        candidate = root / item
        if not candidate.exists():
            raise FileNotFoundError(f"Required release input is missing: {item}")
        if candidate.is_file():
            if not excluded(Path(item)):
                found.add(Path(item))
            continue
        for path in candidate.rglob("*"):
            if path.is_file():
                relative = path.relative_to(root)
                if not excluded(relative):
                    found.add(relative)
    return sorted(found, key=lambda path: path.as_posix())


def git_revision(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_release(version: str, output_dir: Path, root: Path = ROOT) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version) or ".." in version:
        raise ValueError("Release version must be 1-64 safe alphanumeric/dot/underscore/hyphen characters.")
    output_dir.mkdir(parents=True, exist_ok=True)
    files = source_files(root)
    release_dirname = f"air-release-{version}"

    with tempfile.TemporaryDirectory(prefix="air-release-") as temporary:
        stage = Path(temporary) / release_dirname
        stage.mkdir()
        manifest_files = []
        for relative in files:
            source = root / relative
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            manifest_files.append({
                "path": relative.as_posix(),
                "size_bytes": destination.stat().st_size,
                "sha256": sha256(destination),
            })

        manifest = {
            "schema_version": 1,
            "product": "AIR",
            "release_version": version,
            "source_revision": git_revision(root),
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "deployment_profiles": ["onprem-single", "aws-private-single", "aws-saas-multi"],
            "deployment_artifacts": ["compose.local.yml", "docker-stack.yml"],
            "services": [
                {key: value.format(release=version) if isinstance(value, str) else value
                 for key, value in service.items()}
                for service in SERVICE_INVENTORY
            ],
            "files": manifest_files,
            "excluded_runtime_data": [
                ".air-secrets", ".air-local.env", "SQLite/database files", "Terraform state",
                "private signing keys and local build caches",
            ],
        }
        manifest_path = stage / "RELEASE-MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        checksum_lines = [
            f"{item['sha256']}  {item['path']}"
            for item in manifest_files
        ]
        checksum_lines.append(f"{sha256(manifest_path)}  RELEASE-MANIFEST.json")
        (stage / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

        archive = output_dir / f"{release_dirname}.tar.gz"
        with tarfile.open(archive, "w:gz", compresslevel=6) as bundle:
            bundle.add(stage, arcname=release_dirname)

    digest = sha256(archive)
    (output_dir / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(json.dumps({
        "status": "BUILT",
        "archive": str(archive),
        "sha256": digest,
        "files": len(files),
        "source_revision": manifest["source_revision"],
    }, sort_keys=True))
    return archive


def verify_release(archive: Path) -> None:
    archive = archive.resolve()
    sidecar = archive.with_name(archive.name + ".sha256")
    if not archive.is_file() or not sidecar.is_file():
        raise FileNotFoundError("Release archive and matching .sha256 sidecar are both required.")
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    actual = sha256(archive)
    if expected != actual:
        raise ValueError("Release archive checksum does not match its sidecar.")
    with tempfile.TemporaryDirectory(prefix="air-release-verify-") as temporary:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            if any(Path(member.name).is_absolute() or ".." in Path(member.name).parts for member in members):
                raise ValueError("Release archive contains an unsafe path.")
            bundle.extractall(temporary, filter="data")
        roots = list(Path(temporary).iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError("Release archive must contain exactly one top-level release directory.")
        stage = roots[0]
        manifest = json.loads((stage / "RELEASE-MANIFEST.json").read_text(encoding="utf-8"))
        expected_sums = {}
        for item in manifest["files"]:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Release manifest contains an unsafe file path.")
            target = stage / relative
            if not target.is_file() or sha256(target) != item["sha256"]:
                raise ValueError(f"Release file checksum failed: {item['path']}")
            expected_sums[relative.as_posix()] = item["sha256"]
        expected_sums["RELEASE-MANIFEST.json"] = sha256(stage / "RELEASE-MANIFEST.json")
        actual_sums = {}
        for line in (stage / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            digest, filename = line.split("  ", 1)
            relative = Path(filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("SHA256SUMS contains an unsafe file path.")
            target = stage / relative
            if not target.is_file() or sha256(target) != digest:
                raise ValueError(f"Release SHA256SUMS entry failed: {filename}")
            actual_sums[relative.as_posix()] = digest
        if actual_sums != expected_sums:
            raise ValueError("SHA256SUMS does not match the release manifest.")
    print(json.dumps({"status": "VERIFIED", "archive": str(archive), "sha256": actual}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify a checksummed AIR release bundle.")
    parser.add_argument("--version", default="dev")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--verify", type=Path, help="Verify an existing .tar.gz bundle and sidecar.")
    args = parser.parse_args()
    try:
        if args.verify:
            verify_release(args.verify)
        else:
            archive = build_release(args.version, args.output_dir)
            verify_release(archive)
    except (OSError, ValueError, tarfile.TarError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
