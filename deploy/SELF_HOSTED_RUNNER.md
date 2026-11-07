# AIR self-hosted GitHub Actions runner (Windows, Ubuntu/Linux and macOS)

This guide configures a personal PC as a repository-scoped GitHub Actions runner for PR #7. It does not require a cloud VM. Keep the PC powered on, connected to the internet and awake while jobs run.

## What this runner will execute

- Backend: Python 3.12 dependencies and the complete unittest discovery suite.
- Android: Flutter stable, Android SDK, Java 17, Flutter analysis/tests and ARM64 release APK build.

The Android workflow installs Flutter, Android SDK and Java through its actions. The runner itself must have a supported OS and architecture. The same runner must be online for both jobs.

## 1. Create a short-lived registration token

1. Open https://github.com/Analyticsoneview/air-model-engine/settings/actions/runners.
2. Select **New self-hosted runner**.
3. Select the OS and architecture of the PC that will host the runner.
4. Keep the page open and copy the temporary registration token. Do not paste it into chat, a source file, or a GitHub variable/secret. The installer prompts for it locally.

The token expires quickly and is used only to register the runner. It is not the PAT used to clone the repository.

## 2. Install on Windows 10/11 (PowerShell as Administrator)

Open PowerShell as Administrator in a trusted folder, with the repository checked out, then run:

~~~powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\install-github-runner.ps1
~~~

The script downloads the official latest Windows x64 GitHub Actions runner, checks the published SHA-256 digest when supplied, asks for the short-lived registration token, registers the runner with labels air,windows,x64, and installs/starts its Windows service.

For the Windows runner, set the repository variable shown in section 4 to:

~~~text
["self-hosted","windows","x64","air"]
~~~

Keep the Windows PC awake. Windows runner jobs do not require Docker for the backend and Android CI workflows. Docker Desktop is only needed for workflows that explicitly build/run Docker images.

## 3. Install on Ubuntu 22.04/24.04

Use the existing Ubuntu installer from the repository root:

~~~bash
sudo bash deploy/install-github-runner.sh
~~~

Enter the short-lived token when prompted. It installs the runner service and registers labels air,linux,x64.

Use this repository variable:

~~~text
["self-hosted","linux","x64","air"]
~~~

The Linux installer adds the dedicated runner account to the Docker group. Docker access is effectively privileged access to the host; use a trusted, dedicated PC and do not run untrusted pull requests on this runner.

## 4. Point CI at the PC

In repository **Settings → Secrets and variables → Actions → Variables → New repository variable**, create or update:

- Name: AIR_RUNNER_LABELS
- Value: the exact JSON array for the PC OS from section 2 or 3.

The workflows use this variable for backend and Android jobs. If it is absent, they default to GitHub-hosted ubuntu-latest. Do not use Windows labels for a Linux runner or vice versa.

After registration, verify the runner appears as **Online** and **Idle** under repository Settings → Actions → Runners. The runner's labels must include self-hosted, the OS, x64, and air.

## 5. Run and verify PR #7 checks

Open https://github.com/Analyticsoneview/air-model-engine/pull/7. Re-run the failed **AIR Backend Tests** and **AIR Android Lab APK** workflows after the runner is Online.

A successful completion requires:
- Backend: dependency installation succeeds and python -m unittest discover -s tests -v exits 0.
- Android: flutter analyze lib, flutter test, and flutter build apk --release --target-platform android-arm64 all exit 0.
- The Android APK artifact is uploaded and downloadable from the successful run.

Do not treat a queued job, a runner-registration success, or a job that fails before its first step as a passing test. Keep PR #7 unmerged until both workflows pass on the current PR head and the remaining required checks/reviews are satisfied.

## Security and operations

- Register the runner at repository scope, not organization or account scope.
- Never share the registration token. It is short-lived; the runner stores its registration credentials locally.
- Keep the runner PC patched, protected by a screen lock, and free of unrelated sensitive data.
- Do not enable automatic broker orders as part of CI. CI builds and tests only.
- Stop/uninstall the runner service before disposing of or repurposing the PC. Use the runner's local config.cmd remove (Windows) or config.sh remove (Linux) flow with a fresh removal token from GitHub.
- A self-hosted runner can execute repository workflow code. Only run workflows from branches and contributors you trust.

## macOS

The current checked-in shell installer is Ubuntu-specific; do not run it on macOS. For macOS, use GitHub's **New self-hosted runner** page to download the official macOS package for the machine architecture, follow the displayed config.sh instructions, and install/start its service with svc.sh. Register labels air,macOS,ARM64 (Apple Silicon) or air,macOS,X64 (Intel), then set AIR_RUNNER_LABELS to the matching JSON labels. Validate Flutter, Android SDK and Java 17 availability on that host before routing Android CI to it. A dedicated macOS installer can be added if macOS runner support is needed.
