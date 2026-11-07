# AIR Android customer release

The repository includes a manual workflow at .github/workflows/android-release.yml. It builds an ARM64 Flutter APK, signs it with the AIR-owned release keystore, verifies the signature and uploads the APK plus SHA-256 checksum as a 90-day GitHub Actions artifact.

## 1. Create and protect the release keystore

Create this once on a trusted workstation. Keep the original keystore and its passwords in a secure offline backup. Losing the keystore prevents future APK updates from being installed over existing customer installations.

~~~bash
keytool -genkeypair -v \
  -keystore air-model-engine-release.jks \
  -storetype JKS \
  -keyalg RSA -keysize 4096 -validity 10000 \
  -alias air-model-engine
~~~

Do not commit the .jks file. Do not send the keystore or passwords in chat, email, Telegram or issue comments.

## 2. Configure GitHub Actions

Under repository Settings → Secrets and variables → Actions, add:

| Name | Type | Value |
|---|---|---|
| AIR_API_BASE_URL | Variable | Public HTTPS API URL, e.g. https://api.example.com |
| ANDROID_SIGNING_KEY_BASE64 | Secret | Base64 encoding of the complete .jks file |
| ANDROID_KEYSTORE_PASSWORD | Secret | Keystore password |
| ANDROID_KEY_ALIAS | Secret | air-model-engine |
| ANDROID_KEY_PASSWORD | Secret | Key password |

On Ubuntu, create the base64 value with:

~~~bash
base64 -w 0 air-model-engine-release.jks
~~~

On macOS, use base64 < air-model-engine-release.jks | tr -d '\n'. In PowerShell:

~~~powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("air-model-engine-release.jks"))
~~~

Paste the resulting one-line value directly into the GitHub secret field. Do not save it in the repository.

## 3. Build the signed APK

After the workflow is present on the default branch and the Android signing secrets and HTTPS API variable are configured:

1. Open Actions → AIR Android Customer Release.
2. Select Run workflow.
3. Wait for Flutter analysis, tests, APK build and signing verification.
4. Download AIR-Model-Engine-Android-ARM64-Signed from the successful run's Artifacts section.
5. Verify the included SHA-256 checksum before distributing the APK.

The workflow currently targets ARM64 Android devices. It does not publish to Google Play. A Play Store release requires a separate Play Console account, app signing configuration and store review.

## 4. Customer installation

Distribute the signed APK only over the AIR HTTPS app portal or another authenticated channel. Android users may need to permit installation from that specific source. Customers must submit a device access request and wait for AIR administrator approval.

An APK artifact is not a live-tested release. Before public distribution, install it on supported physical Android devices and verify cold start, secure session restore, HTTPS API access, logout/revocation and upgrade installation using the same signing key.
