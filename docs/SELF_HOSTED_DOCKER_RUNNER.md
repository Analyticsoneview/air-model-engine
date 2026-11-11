# AIR self-hosted Docker integration runner

## Current CI finding

The PostgreSQL and Redis integration jobs now start on the self-hosted Windows runner and reach the Docker preflight step. The preflight fails because the runner service runs as **NT AUTHORITY\NETWORK SERVICE** and cannot open the Docker Desktop Linux-engine named pipe:

`//./pipe/dockerDesktopLinuxEngine: Access is denied`

This is a runner-account permission issue, not a PostgreSQL migration or Redis test failure. The test containers are not created.

## Recommended Windows fix

Use a dedicated local Windows account for the GitHub Actions runner. Do not grant Docker access to `NetworkService`: control of the Docker engine is effectively host-administrator access.

1. Install Docker Desktop and enable the Linux container / WSL 2 engine.
2. Create a dedicated account such as `AIRRunner`.
3. Add that account to the local `docker-users` group:
   ```powershell
   Add-LocalGroupMember -Group 'docker-users' -Member '.\AIRRunner'
   ```
4. Sign in to Windows as that account at least once and start Docker Desktop. Confirm the Linux engine is running.
5. Open **Services** (`services.msc`), find the GitHub Actions runner service for `Analyticsoneview/air-model-engine`, open **Properties → Log On**, and change the service account from `Network Service` to the dedicated `AIRRunner` account. Enter its password and restart the service.
6. In a PowerShell session running as `AIRRunner`, verify:
   ```powershell
   docker version
   docker info
   docker run --rm hello-world
   ```
7. Confirm the runner service is online, then rerun the PostgreSQL and Redis integration workflows.

Do not store the Windows account password in the repository, workflow YAML, or a diagnostic ZIP.

## Alternative: in-house Linux runner

For a more stable CI setup, register a dedicated Ubuntu runner on an in-house Linux machine or VM, install Docker Engine, and assign a label such as `air-docker`. The integration workflows can then use that runner with Bash and Docker Engine. This avoids coupling CI to a logged-in Windows desktop session and does not require cloud hosting or Kubernetes.

## Current safety behavior

The integration workflows fail closed when Docker is unavailable. They do not skip tests, silently fall back to SQLite, or mark the PostgreSQL/Redis integration gates as passed. Cleanup steps are guarded so a missing Docker engine does not mask the original preflight error.
