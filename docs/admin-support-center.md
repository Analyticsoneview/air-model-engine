# AIR Admin and Customer Support Center

## Scope

The support center provides customer-owned support tickets and an administrator queue. It does not expose broker credentials, order mutation, or another customer's ticket content.

## Customer APIs

- `POST /api/v1/customer/support/tickets`: create a ticket with subject, category and first message.
- `GET /api/v1/customer/support/tickets?limit=100`: list only the authenticated customer's tickets.
- `GET /api/v1/customer/support/tickets/{ticket_id}`: retrieve one owned ticket and its activity.
- `POST /api/v1/customer/support/tickets/{ticket_id}/replies`: append a customer reply. Closed tickets cannot be reopened through this endpoint.

Customer identity is normalized to the E.164 mobile identity; device/request IDs are not treated as separate customers.

## Admin APIs

- `GET /api/v1/admin/support/tickets?status=OPEN&limit=200`: prioritized support queue.
- `PUT /api/v1/admin/support/tickets/{ticket_id}`: append an admin reply, change status or priority, and optionally assign the ticket to an administrator.

Only SUPER_ADMIN and ADMIN roles can access the queue and update tickets. RESEARCH_ADMIN is denied by the administrator-management dependency.

## Ticket lifecycle

Statuses: OPEN, IN_PROGRESS, WAITING_CUSTOMER, RESOLVED, CLOSED.
Priorities: LOW, NORMAL, HIGH, URGENT.
Categories: ACCOUNT, BILLING, BROKER, TECHNICAL, GENERAL.

Every create, reply, status change, priority change and assignment appends an activity event. Event rows are immutable in SQLite and PostgreSQL. Customer queries always filter by authenticated customer identity.

## Persistence and rollout

Alembic revision `0011_admin_support_center` adds ticket and event tables plus indexes and an immutable-event trigger. PostgreSQL is selected when AIR_CUSTOMER_DATABASE_URL or AIR_DATABASE_URL is configured. SQLite is retained only as the local development/test fallback. Apply `python -m alembic upgrade head` before starting an instance configured for PostgreSQL.
