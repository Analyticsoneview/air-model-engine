# AIR Global Strategic Master Plan

**Status:** FROZEN STRATEGIC DIRECTION — 17 November 2026  
**Owner:** AIR Product and Programme Leadership  
**Repository:** `Analyticsoneview/air-model-engine`  
**Planning horizon:** Long-term, stage-gated global expansion  
**Document type:** Strategy baseline; not a financial forecast, legal opinion, exchange-data licence or launch authorization.

## 1. Strategic mandate

AIR (Analytical Investment Research) will be developed as a global financial research technology ecosystem. It is not limited to a retail stock screener, charting tool, options terminal or broker front end.

**Positioning:** More research depth. Better-connected intelligence. Greater control. One integrated platform.

AIR will connect market data, research methodologies, quantitative validation, derivatives analytics, workflow orchestration, portfolio risk, developer integrations and enterprise deployment through one product architecture.

The competitive basis is breadth and integration, evidence quality, workflow productivity, extensibility, customer control and deployment choice—not lowest price.

## 2. Frozen annual business ambitions

| Business | Annual revenue ambition | Interpretation |
|---|---:|---|
| B2C | **₹10,000 crore** | Long-term annual recognised revenue target |
| B2B | **₹10 crore to ₹1,00,000 crore** | Staged annual revenue ambition; ₹10 crore is an early commercial milestone and ₹1,00,000 crore is an extreme global stretch ambition |
| Geography | **Global** | India commercial validation first; global-ready architecture from inception |

These figures are strategic ambitions, not forecasts, commitments, current run-rate or valuation targets. They exclude GMV, assets under management, customer trading turnover and valuation. Report B2C and B2B separately and also report consolidated revenue. Eliminate intercompany and channel double counting. Distinguish gross billings, recognised net revenue, pass-through data/provider charges, implementation revenue and recurring revenue.

The ₹1,00,000 crore B2B ambition is not achievable through conventional seat licences alone. It would require global institutional distribution, embedded/white-label adoption, infrastructure and API usage, strategic partnerships and potentially inorganic expansion. It must remain a stretch scenario until supported by independently validated market sizing, customer economics and distribution capacity.

## 3. Strategic principles — non-negotiable

1. **One product, multiple deployment models:** common domain services and release train across self-hosted/on-premises, private deployment and SaaS. AWS is optional, not an architectural prerequisite. Docker Swarm remains a supported self-hosted target; no Kubernetes-only dependency.
2. **Integration over feature count:** every capability should use common identity, entitlements, data contracts, audit and workflow services.
3. **Evidence before outputs:** market-data timestamps, provenance, licensing scope, methodology version, calculation inputs and validation lineage must be traceable.
4. **Risk and governance by design:** tenant isolation, privacy, least privilege, auditability, secure secrets, model governance and explicit customer approvals.
5. **Customer-owned research stays private:** no cross-customer reuse, training or distribution of confidential customer strategies, positions or research without explicit rights and consent.
6. **No unsupported market-data claims:** distinguish delayed, end-of-day, historical, real-time, tick and order-book coverage. Data redistribution and derived-data rights require provider/exchange approval.
7. **Regulatory boundaries are product controls:** software, research, advice, marketing and broker execution are separately classified and gated. Disclaimers alone are not a compliance control.
8. **Commercial viability is a release criterion:** every paid capability has a defined customer, value proposition, entitlement, cost-to-serve, pricing basis, support model and legal/data clearance.
9. **Global-ready, region-aware:** currency, tax, time zones, calendars, languages, privacy and data-residency policies are explicit configuration—not hard-coded assumptions.
10. **Build versus partner deliberately:** build core research IP and orchestration; partner for licensed data, payments, distribution, identity verification and specialist capabilities where that is safer or faster.

## 4. Business engines and revenue architecture

AIR will operate multiple commercial engines over the same platform.

| Engine | Customer | Monetisation |
|---|---|---|
| B2C research platform | Individual traders, investors and researchers | Free-to-paid subscriptions, annual plans, premium modules and usage add-ons |
| Professional workspaces | Advanced users and small research teams | Higher-tier subscriptions, seats, compute and storage allowances |
| Institutional platform | Brokers, asset managers, research teams, family offices and financial institutions | Annual platform licences, seats, modules, SLA and implementation |
| Embedded / white-label | Brokers, fintechs and wealth platforms | Platform fee, active-user pricing, usage/API fees and implementation |
| Developer platform | Fintech developers and integration partners | API tiers, metered calls, event/webhook usage and partner licences |
| Data and intelligence services | Eligible institutions and technology partners | Licensed data products, derived analytics and contracted data services, only where rights permit |
| Quant research compute | Professional and institutional users | Compute credits, backtest jobs, optimisation and simulation usage |
| Education and certification | Individuals, institutions and developers | Course fees, institutional training and certification; kept separate from regulated advice/research services |

Do not count payment-gateway pass-through, exchange/provider pass-through or partner GMV as AIR revenue. Recognise revenue under the applicable accounting policy. Separate recurring software revenue from professional services and implementation.

### 4.1 B2C commercial design

Indicative India launch hypotheses (not approved public prices; before applicable taxes and data charges):

| Edition | Indicative monthly price | Intended value |
|---|---:|---|
| Free | ₹0 | Product discovery, limited dashboard, basic charts and limited screening |
| Essential | ₹499 | Personal research, watchlists, alerts and standard technical analysis |
| Trader | ₹999 | Advanced screening, derivatives analytics, strategy tools and paper research |
| Professional | ₹1,999 | Advanced backtesting, multi-strategy research, portfolio/risk analytics and workflows |
| Elite | ₹3,499 | Higher compute/data limits, advanced research and integrations |
| Add-ons | Usage/plan based | Additional compute, storage, approved data entitlements and premium modules |

Prices must be tested against willingness to pay, conversion, churn, gross margin, data cost and competitor alternatives. Do not publish a tier until its feature entitlements and operational costs are enforceable.

### 4.2 B2B commercial design

- **Team:** per-seat and workspace licence with role-based controls.
- **Business:** annual platform licence, admin controls, shared research, reporting and support.
- **Institutional:** negotiated annual contract, modules, environments, SLAs, integrations and security requirements.
- **Embedded/OEM:** minimum platform commitment plus active-user/API usage and agreed revenue share.
- **On-premises/private deployment:** annual software licence, implementation, upgrades and support; infrastructure and third-party data licences itemised.
- **Data/API/compute:** contracted usage tiers with quotas, overage controls and customer-visible metering.

B2B pricing is based on seats, environments, regions, modules, data rights, API/compute volume, storage, support tier, SLA and deployment complexity. Do not price an enterprise account solely by retail feature count.

## 5. Product architecture

AIR is a modular platform with shared services and bounded domain capabilities.

### 5.1 Shared platform foundation

- Identity, customer, organisation, tenant, membership and role service.
- Subscription catalogue, contract, billing, tax, payment, invoice and entitlement service.
- Unified financial data fabric: source registry, instrument identity, calendars, corporate actions, provenance, schema/version and quality/reconciliation.
- Event and workflow fabric: durable event intake/outbox, RabbitMQ task routing, schedulers, retries, idempotency, audit and notifications.
- Research metadata, methodology registry, versioning, reproducibility and audit.
- Security, consent, privacy, data-retention, export and audit controls.
- Observability, metering, cost attribution, quotas and service-level reporting.
- Deployment manager, tenant provisioning and regional configuration.

### 5.2 Research product domains

1. Market intelligence and screening.
2. Charting and technical analysis.
3. Derivatives, options and volatility analytics.
4. AIR QOC and other governed methodology engines.
5. Quant research, backtesting, optimisation and simulation.
6. Portfolio, exposure and risk analytics.
7. Research workspaces, reports and collaboration.
8. Workflow Studio, alerts and event-driven automation.
9. Broker connectivity and controlled order-ticket preparation.
10. Developer APIs, SDKs, webhooks and integration marketplace.

Workflow orchestration must invoke existing domain services; it must not duplicate their calculations. Broker execution remains disabled unless a separate, approved execution capability and all applicable controls are established. Each order must retain explicit customer approval under the current operating decision.

### 5.3 Deployment and regional architecture

- **Self-hosted/on-premises:** first-class, Docker Swarm supported, persistent services, Docker secrets, backup/restore and one-click installation/readiness.
- **Private deployment:** customer-controlled infrastructure, private networking, customer data boundaries and contracted support.
- **SaaS:** tenant-isolated control plane, regional data plane, per-tenant quotas, metering, backup, restore and support operations.
- **Hybrid:** customer-owned sensitive data with selected hosted control/compute functions only where contract and law permit.

The application and domain APIs remain common. Deployment adapters implement storage, identity, messaging, secrets, networking, observability and provisioning. No feature may silently require AWS or Kubernetes.

### 5.4 Global market model

Implement market adapters and reference data for each enabled venue/segment. Initial priority is India (NSE/BSE/MCX/NCDEX), then US venues, followed by selected UK, Europe and Asia-Pacific markets. GIFT City instruments are represented as distinct instruments/venues where applicable.

Every market adapter must define instrument identity, currency, timezone, calendar, session rules, corporate actions, source entitlements, history coverage, data-quality checks and reconciliation. Broker global-access catalogues are tradability overlays, not canonical exchange masters.

## 6. Global trust, compliance and data controls

- Legal classification is based on actual activities, customer journey, fees, communications, recommendations and execution—not product labels.
- Paid/public security-specific research recommendations, personalised investment advice and automated execution remain disabled until applicable legal assessment, registration/authorisation and operational controls are evidenced.
- Private internal research is owner-scoped and not for distribution by default; it is not a blanket exemption from market-abuse, data-licensing, privacy or other obligations.
- Broker integrations require broker-by-broker permissions, API terms, order-flow review and explicit customer authorisation.
- Real-time data, derived data, redistribution, storage and display rights must be approved per exchange/provider and geography.
- Implement privacy-by-design, data minimisation, consent, retention, deletion/export, breach response, encryption, key management, access reviews and independent security testing.
- AI/model outputs must be explainable, versioned, monitored and traceable to source evidence; no unsupported performance or accuracy claims.
- Global launch requires local legal, tax, privacy, payments, consumer-protection, sanctions and data-residency review.

The existing SEBI compliance framework and its evidence register remain mandatory release controls. This strategy is not legal advice, regulatory approval or a claim of compliance.

## 7. Financial milestones — stage gates, not calendar promises

The following are annual recognised revenue milestones. They are programme checkpoints, not dated forecasts.

| Stage | B2C annual revenue checkpoint | B2B annual revenue checkpoint | Required proof |
|---|---:|---:|---|
| Validation | ₹1–10 crore | ₹1–10 crore | Paying cohorts, retention, compliant offer, repeatable onboarding and reliable support |
| Product-market fit | ₹25–100 crore | ₹25–100 crore | Repeatable acquisition, positive contribution margin and first reference customers |
| National scale | ₹250–1,000 crore | ₹250–1,000 crore | Multi-channel distribution, robust unit economics, operational resilience |
| International expansion | ₹1,000–3,000 crore | ₹1,000–5,000 crore | Localised products, regional partners, multi-currency billing and regional compliance |
| Global scale | ₹3,000–10,000 crore | ₹5,000–25,000 crore | Multi-region platform, strong retention, enterprise references and diversified revenue |
| Extreme stretch | ₹10,000 crore | Up to ₹1,00,000 crore | Global infrastructure/embedded distribution scale, major institutional penetration and/or inorganic expansion |

The B2B ₹1,00,000 crore checkpoint is deliberately marked extreme stretch. Reforecast only after market sizing, customer pipeline, contract-value evidence, delivery capacity, capital requirements and audited revenue support it.

### 7.1 Revenue mathematics and operating metrics

At ₹1,000 average monthly B2C revenue per paying customer, ₹10,000 crore annual revenue implies approximately 8.33 million average paying customers. This is arithmetic only; actual mix, discounts, taxes, churn and geography will change the required base.

Track at minimum:
- ARR/MRR and recognised revenue by B2C, B2B, region, product and channel.
- Paid active customers, conversion, ARPU, retention, cohort churn and expansion.
- CAC, payback period, LTV/CAC and contribution margin by channel.
- B2B pipeline, win rate, average contract value, sales cycle, renewal and net revenue retention.
- Gross margin by subscription, API, data, compute, implementation and deployment model.
- Data/provider cost per active customer and per unit of usage.
- Uptime, data freshness/completeness, job success, backtest reproducibility and incident recovery.
- Security, privacy, compliance and data-licence evidence coverage.

Initial management guardrails to validate against real cohorts: LTV/CAC at least 3x, B2C CAC payback within 6 months, B2B CAC payback within 18 months, B2B net revenue retention above 110%, and software gross margin trending above 75%. These are proposed internal targets, not achieved metrics or universal benchmarks. Adjust by segment and actual unit economics.

### 7.2 B2C scale equation

B2C revenue = average paying customers × average monthly net revenue per paying customer × 12.

The ₹10,000 crore ambition requires a large free-to-paid funnel, strong retention, distribution partnerships, multi-country expansion, tiered pricing and premium usage services. Do not assume low pricing alone will produce mass adoption.

### 7.3 B2B scale equation

B2B revenue = recognised annual platform/licence revenue + embedded/API/data/compute revenue + eligible services revenue, net of pass-through and intercompany duplication.

The upper stretch target requires platform distribution beyond direct enterprise sales: embedded/OEM, global partners, infrastructure services and potentially strategic acquisitions. Seat licences alone are insufficient.

## 8. Go-to-market strategy

### B2C
- Free product-led acquisition with transparent limits.
- Time-limited professional trials with clear conversion terms.
- Educational content and training separated from regulated research/advice.
- Referral programmes with fraud controls and transparent terms.
- Broker/fintech partnerships where permitted.
- Localised pricing, payments, support and product experience.
- Customer success, onboarding and lifecycle messaging with recorded consent.

### B2B
- Named-account sales for brokers, fintechs and institutions.
- Partner-led distribution and solution integrators.
- Paid proof-of-concept with measurable acceptance criteria.
- Security, architecture, data-rights and compliance packs.
- Annual contracts, implementation, SLA and renewal management.
- Reference customers and case studies with customer permission.

## 9. Strategic risks and countermeasures

| Risk | Required countermeasure |
|---|---|
| Overbuilding before product-market fit | Stage funding and delivery on customer evidence |
| Exchange/provider data restrictions | Contractual rights matrix, entitlement enforcement and audit |
| Regulatory classification | Feature-level legal gates and release blocks |
| High customer acquisition cost | Cohort economics, partner distribution and retention |
| Compute/data cost overwhelms subscription | Metering, quotas, cost attribution and usage pricing |
| Tenant or customer data leakage | Isolation tests, least privilege, encryption and independent testing |
| Multi-region complexity | Region-specific adapters and staged market entry |
| Enterprise customisation fragmentation | Configuration and extension points, not customer-specific forks |
| AI overclaiming | Evidence lineage, model governance and conservative claims |
| Revenue concentration | Diversified customers, channels, regions and product engines |
| Founder/key-person dependency | Documented operations, delegated ownership and succession |
| Extreme B2B ambition unsupported by market | Independent market sizing and periodic target revalidation |

## 10. Governance and review

- Quarterly strategy review: market evidence, customer economics, competitive position, risks and investment allocation.
- Monthly operating review: revenue, pipeline, cohorts, product adoption, reliability, cost and compliance evidence.
- Every gate has a named owner, scope, acceptance tests, dependency, evidence and explicit status.
- Strategy changes require a versioned decision record; frozen targets are not silently rewritten.
- No revenue, customer, deployment, compliance or market coverage claim without verifiable evidence.

## 11. Frozen decisions

1. B2C annual revenue ambition: ₹10,000 crore.
2. B2B annual revenue ambition: staged from ₹10 crore to ₹1,00,000 crore extreme global stretch.
3. Geographic ambition: global.
4. Product identity: integrated financial research technology ecosystem.
5. Product architecture: one product, modular domains, multiple deployment models.
6. Commercial model: B2C + B2B + embedded/white-label + API + licensed data/analytics + compute + eligible education/services.
7. Deployment: self-hosted/on-premises first-class; SaaS and private deployment supported; AWS optional.
8. Differentiation: research depth, integration, evidence, workflow productivity, flexibility, trust and control—not lowest price.
9. Regulatory and data-licensing controls are release gates.
10. Financial milestones are stage gates and must be supported by verified economics.

**Master positioning:** AIR is the integrated financial research technology ecosystem that individuals use, professional teams depend on and financial technology companies integrate.
