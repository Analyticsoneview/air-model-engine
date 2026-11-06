# AIR Model Engine — Internal Lab

Flutter mobile shell for internal Android validation.

## Build
GitHub Actions runs the **AIR Android Lab APK** workflow on pushes to `main`.
The workflow creates the Android platform project, resolves Flutter dependencies, runs static analysis, builds a debug APK, and uploads it as a 30-day workflow artifact.

## Current scope
This first lab build validates app launch, navigation and placeholder screens for Dashboard, Options, AIR QOC and Data Center. It does not yet provide live NSE feeds, production QOC signals, broker connectivity or order execution.

See the full architecture and backend starter in the separate AIR Model Engine lab source package.
