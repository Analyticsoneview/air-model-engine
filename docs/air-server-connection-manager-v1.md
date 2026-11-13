# AIR Server Connection Manager v1

## Purpose
One AIR client supports local development, private staging, AWS production and custom deployments. The API endpoint is selected at runtime; business logic remains deployment-independent.

## Profiles
- Local development: browser on the AIR PC may use http://localhost:8000; native Android must use the PC trusted-LAN IP.
- Staging: HTTPS endpoint only.
- AWS production: HTTPS endpoint only. No AWS hostname, credentials or infrastructure assumptions are embedded in the client.
- Custom: HTTPS required except trusted private-LAN HTTP during local development.

## Connection lifecycle
1. Select a deployment profile and enter its API base URL.
2. Validate URL syntax, transport policy and platform-specific loopback rules.
3. Clear active access tokens before changing server.
4. Call GET /health with an eight-second timeout.
5. Save endpoint and profile only after a healthy response.
6. Continue to the existing AIR access gate.

## Security
- Never place API keys, database credentials or AWS secrets in the PWA.
- Never send a token issued by one server to another server.
- Staging and production require HTTPS.
- Local HTTP is only for browser localhost or trusted private-LAN testing.
- Production CORS, secure cookies, domain and TLS remain deployment configuration.

## AWS portability
The AWS endpoint is supplied at deployment/runtime. The app does not depend on API Gateway, ALB, ECS, EC2 or an AWS SDK. Infrastructure can be selected later without changing this client.

## UI direction
The screen follows AIR's shared premium dark/light theme, gold brand accent, card/control tokens and an information-rich hierarchy: environment selection, endpoint context, validation and security guidance. It uses responsive layout and AIR branding rather than copying another product's identity.

## Validation
Run flutter analyze lib and flutter test from mobile/. PWA and Android workflows validate the shared Flutter source.
