# Gate 17F — Commercial catalogue and entitlement baseline

**Slice:** 17F-0 / initial 17F-1 contract  
**Status:** IMPLEMENTED IN CODE — PR REVIEW REQUIRED  
**Billing:** Annual B2C and annual B2B contracts  
**Commercial status:** Pre-launch; no public prices and no payment collection.

## Decisions

- Paid B2C plans are annual. AIR Free remains free.
- B2B Team, Business and Institutional contracts are annual and quote-based.
- Prices are not published by the API. Currency, taxes, provider data charges and regional price books are deferred until finance, tax, data-rights and payment review.
- Existing `DAILY`, `MONTHLY`, `SIX_MONTHS` and `YEARLY` subscription records remain readable for backward compatibility. They are not silently converted into the new catalogue.
- Existing active legacy subscriptions resolve only to the legacy `strategy_workspace` entitlement in the new catalogue contract. Existing API access behaviour is unchanged in this slice.
- Inactive subscriptions receive the free feature set. Unknown active plan codes fail closed with no features.
- Personalised advice, paid public security-specific recommendations, automated broker execution, broker order submission, unlicensed data redistribution and customer research publication are globally restricted and cannot be granted by a plan.

## API

- `GET /api/v1/subscription/catalogue`: public pre-launch B2C and B2B product catalogue.
- `GET /api/v1/subscription/me`: existing customer subscription response extended with effective catalogue entitlements.

The catalogue is provider-neutral and database-neutral. No checkout, payment provider, invoice, renewal, refund, tax calculation, contract assignment or B2B tenant provisioning is enabled.

## Feature keys

B2C keys include dashboard, watchlists, charts, screening, historical analysis, options analytics, OI/volume analytics, strategy builder, paper trading, backtesting, workflow alerts, portfolio risk, custom indicators, multi-market analytics, compute limits and approved integrations.

B2B keys include organisation workspace, seat management, shared administration, audit history, enterprise reporting, API access, workflow governance, private deployment, white-label, custom SLA and regional deployment options.

A catalogue feature key is a product entitlement definition, not proof that its corresponding runtime capability is implemented or that third-party data rights exist. Runtime enforcement must be added to each feature endpoint in its owning implementation gate.

## Next slices

1. 17F-2: versioned subscription/contract ledger with annual start/end, grace, cancellation, suspension, renewal and immutable lifecycle events.
2. 17F-3: usage metering and quotas for seats, API, compute, storage and permitted data.
3. 17F-4: payment provider abstraction and sandbox-only verified webhook processing.
4. 17F-5: invoices, tax configuration, refunds and settlement reconciliation.
5. 17F-6/7: customer lifecycle, organisations, memberships and seat administration.
6. 17F-8: enterprise licence activation and deployment binding.

Do not activate paid checkout until the payment, legal, tax, security, data licensing and operational release evidence is complete.
