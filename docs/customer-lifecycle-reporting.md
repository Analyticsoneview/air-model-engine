# AIR customer lifecycle and reporting

## Customer identity and classification

- Customer identity is the validated E.164 mobile number. Device IDs identify access requests, not customers.
- One customer register row is produced per mobile identity. Additional device requests do not increase customer counts.
- The first request for a mobile identity is NEW; later device requests are EXISTING.
- The customer register's as_of_date parameter classifies a customer as NEW when the first registration date equals that date and EXISTING when the customer was registered earlier. A later approval does not change the first registration timestamp or the original request classification.

## Lifecycle dates

air_customer_lifecycle stores first_registered_at, first_approved_at, first_rejected_at and first_plan_availed_at.
The first successful approval and first plan assignment are written once. Repeated decisions and subsequent plan assignments do not overwrite these first-event dates.

## Approval audit

Every approval, rejection or block appends a row to air_access_decision_history. The record contains request/customer IDs, previous and new statuses, administrator ID and role, note, TOTP counter, verification timestamp/reference, device ID and request context.
PostgreSQL and SQLite enforce append-only behavior for the decision history. The API returns both UTC timestamps and IST display timestamps. The raw TOTP code or authenticator secret is never stored in the audit row.

## Subscription lifecycle

air_customer_subscriptions remains the current entitlement record. air_customer_subscription_history records each successful plan assignment, including the assigning administrator. Approval does not assign a plan. The Admin API rejects plan assignment unless the customer is registered and currently approved.
The first plan date is retained in air_customer_lifecycle.first_plan_availed_at. For records that existed before subscription history was available, the migration can only use the legacy subscription row's updated_at timestamp as its best available assignment timestamp; older overwritten plan assignments cannot be reconstructed from the legacy current-state-only table.

## Admin APIs

- GET /api/v1/admin/customers: customer register and independent date filters: registered_from/registered_to, approved_from/approved_to, rejected_from/rejected_to, plan_from/plan_to, expiry_from/expiry_to.
- GET /api/v1/admin/access-decisions: decision history with optional IST date range.
- GET /api/v1/admin/customer-reports/daily?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD: daily new registrations, existing-customer requests, approvals, rejections, pending requests, first plans and approved customers without a plan. Date boundaries are interpreted in Asia/Kolkata.

The daily report reconstructs request/customer status as of each report date from append-only decision events. It does not count device requests as new customers.