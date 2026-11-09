# AIR one-command self-hosted setup (Windows 10/11 and Linux)

The repository now includes a one-command setup utility. It uses your local GitHub CLI sign-in to request a short-lived runner token directly from GitHub, registers this PC, sets the CI runner label variable, waits for the runner to come online, then dispatches and watches the backend and Android workflows.

## Before the first run

- Have the AIR repository available locally and check out `feat/air-telegram-alerts`. Git is required to run from the repository checkout.
- You do **not** need to install GitHub CLI manually. AIR-SETUP installs it using winget/Chocolatey on Windows or apt/dnf on supported Linux distributions.
- Use a GitHub account with repository administration permission for `Analyticsoneview/air-model-engine` (runner registration and repository Actions variables require admin access).
- Keep the PC powered on, awake, and connected to the internet.
- The first run installs GitHub CLI if needed, then opens GitHub browser/device authentication if you are not already signed in. Complete that approval locally. Future runs reuse the saved sign-in.
- Do not paste any token into chat. AIR-SETUP requests and handles the short-lived runner token locally.

## Run on Linux

From the repository root, on branch `feat/air-telegram-alerts`:

~~~bash
bash AIR-SETUP.sh
~~~

The script requests elevation to install GitHub CLI (if missing) and the runner service. It registers labels for Linux and CPU architecture, configures `AIR_CI_RUNNER_LABELS`, waits for Online status, then runs `backend-tests.yml` and `android-lab.yml` and waits for their results.

Supported Linux distributions are Ubuntu, Debian, Fedora, RHEL, Rocky Linux and AlmaLinux with systemd. Alpine, non-systemd installations and unlisted distributions are not supported by this installer.

## Run on Windows 10/11

Open **PowerShell as Administrator** in the repository root, on branch `feat/air-telegram-alerts`:

~~~powershell
Set-ExecutionPolicy -Scope Process Bypass
.\AIR-SETUP.ps1
~~~

Or from Command Prompt:

~~~bat
AIR-SETUP
~~~

Windows setup registers labels for Windows x64, configures `AIR_CI_RUNNER_LABELS`, waits for Online status, then runs and watches the backend and Android workflows. Windows 10/11 x64 is supported; ARM Windows is not covered by this installer.

## What it changes and what it does not

- Registers one repository-scoped GitHub Actions runner on this PC.
- Sets the repository Actions variable `AIR_CI_RUNNER_LABELS` to the detected OS/architecture labels.
- Dispatches the backend and Android workflows on PR branch `feat/air-telegram-alerts`.
- Does **not** set `AIR_RUNNER_LABELS`. Linux-only Docker Buildx/PWA workflows remain on their existing Linux runner until Docker is deliberately configured.
- Does not enable automatic broker orders or interact with broker credentials.
- Does not merge PR #7.

## Success criteria

The command exits successfully only when the runner is Online and both dispatched workflows complete successfully. The Android workflow must upload the ARM64 release APK artifact. If a job fails, the command returns a failure and the GitHub Actions run contains the diagnostic logs.

Open https://github.com/Analyticsoneview/air-model-engine/pull/7 to review the workflow runs and APK artifact.

## Security

- Use a trusted, dedicated PC. Self-hosted runners execute repository workflow code with the permissions of the runner account.
- The GitHub CLI session must belong to a repository administrator. The runner token is generated locally, held temporarily in process memory/environment, and is not committed or stored as a repository variable.
- On Linux, the runner uses a dedicated `airrunner` account. Docker group membership is not granted automatically by AIR-SETUP.
- Keep PR #7 unmerged until the current PR head has successful required checks and all review requirements are met.
- To remove the runner, use the local runner's `config.sh remove` (Linux) or `config.cmd remove` (Windows) with a fresh removal token, then remove the runner entry in repository Settings → Actions → Runners.
