# AIR SaaS tenant object storage API

Gate 17A adds authenticated object storage for the `aws-saas-multi` profile. It does not change the on-prem `onprem-single` or private AWS `aws-private-single` storage path.

## API

All endpoints require a valid AIR customer bearer token. The API derives the tenant and customer identity from the verified token/request context; callers cannot provide a tenant ID or bucket name.

| Method | Endpoint | Purpose |
|---|---|---|
| `PUT` | `/api/v1/tenant/objects/{object_key}` | Upload raw request bytes |
| `GET` | `/api/v1/tenant/objects` | List stored object metadata |
| `GET` | `/api/v1/tenant/objects/{object_key}` | Download an object |

Nested keys are supported, for example `reports/2026/daily.csv`. The request body is the object bytes; send the media type in `Content-Type`. The default maximum is 25 MiB per object. `AIR_TENANT_MAX_UPLOAD_BYTES` can lower this limit but cannot raise it above 25 MiB.

Example:

```bash
curl --fail-with-body \
  -X PUT \
  -H "Authorization: Bearer $AIR_CUSTOMER_TOKEN" \
  -H "Content-Type: text/csv" \
  --data-binary @daily.csv \
  "https://air.example.com/api/v1/tenant/objects/reports/daily.csv"
```

## Tenant isolation and quota model

- Tenant identity comes from the authenticated request context, never from a request field or URL.
- OWNER, ADMIN and MEMBER roles may upload; READ_ONLY members may list and download but cannot upload.
- PostgreSQL row-level security protects `air_tenant_objects`; tenant-scoped row locking serializes quota reservations.
- `air_tenants.storage_used_bytes` is reserved transactionally before the S3 write. Concurrent uploads cannot both spend the same remaining quota.
- Every object key is immutable. Reusing a key with identical size and SHA-256 is idempotent; different content at an existing key returns HTTP 409.
- The S3 provisioner verifies the supplied SHA-256 against the actual bytes before upload. Downloads verify both byte length and SHA-256 against PostgreSQL metadata before returning data; an integrity mismatch fails closed with HTTP 502.
- The PostgreSQL registry independently verifies active tenant membership for every reserve, completion, list and download-metadata operation. Read-only roles cannot reserve or complete uploads even if a caller bypasses the HTTP route.
- A `PENDING` reservation is retained after an ambiguous S3/network failure. Retrying the same key and content verifies S3 object metadata and completes the existing reservation without double-counting.
- S3 objects use the provisioned tenant bucket and tenant prefix, server-side encryption, private bucket controls and TLS-only bucket policy.
- The API lists and downloads only objects recorded as `STORED` for the authenticated tenant.
- Empty objects, unsafe path segments, invalid digests, oversized bodies and quota overflow are rejected.

## Responses and errors

- Upload returns `stored` or `already_stored`, object metadata, current quota usage and the configured quota.
- HTTP 401/403: missing, invalid or inactive customer/tenant access.
- HTTP 409: non-SaaS deployment profile, immutable-key conflict or storage quota exhausted.
- HTTP 413: per-request upload limit exceeded.
- HTTP 422: invalid object key, media type or metadata.
- HTTP 502: S3 operation could not be confirmed. Retry the same key and bytes to resume the pending reservation.

## Migration and rollout

Alembic revision `0021_tenant_object_storage` adds the tenant usage counter and object metadata ledger. Apply `alembic upgrade head` after taking the normal database backup. The migration does not create AWS resources or change tenant buckets.

This gate is code/CI acceptance only. Live AWS bucket access, production quota behaviour, lifecycle/retention policy and penetration testing remain in the AWS deployment acceptance register. Object deletion and overwrite are intentionally not exposed in this first release so quota accounting remains consistent with S3 bucket versioning.
