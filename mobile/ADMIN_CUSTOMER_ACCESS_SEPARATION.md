# AIR administrator/customer application separation

## Customer application

The default Flutter entry point is `lib/main.dart`. It exposes customer mobile-number onboarding, the customer dashboard, subscriptions and customer-facing modules. It does not import, link to, or display the administrator console or legacy AIR administration screen. Customer server switching leaves the administrator token untouched.

## Administrator application

The dedicated administrator entry point is `lib/admin_main.dart`. It opens only the AIR Administrator Console, which requires administrator email, password and TOTP MFA. Build this target only in the trusted staff release pipeline:

```bash
cd mobile
flutter build apk --target lib/admin_main.dart --release
```

Before distributing a staff APK independently from the customer APK, assign it a distinct Android application ID and signing configuration in the staff release pipeline. Do not distribute the administrator build to customers.

## Authorization boundary

The administrator console uses the separate `air_admin_access_token` and `/api/v1/admin/auth/*` endpoints. Protected administrator APIs use the backend `require_admin` dependency and role checks. Customer sessions use `air_access_token` and the customer access gate. Hiding administrator controls in the customer UI is not the security boundary: backend authorization remains mandatory.

## Session isolation

Customer server setup and customer server switching must not delete or overwrite `air_admin_access_token`. Administrator logout revokes the administrator session and deletes only its own token. Server URL configuration is shared by the current Flutter package; staff and customer deployments must point to the intended AIR environment.
