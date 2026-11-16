# AIR SEBI regulatory compliance and investor-protection framework

## 1. Programme decision and operating model

Approved product direction (programme decision; not a regulatory approval):
- Operating model: **hybrid** — software/analytics platform plus a separately governed research service.
- Broker execution: **controlled/manual approval** — AIR may prepare an order ticket, but the customer must review and explicitly approve each order. No unattended, scheduled, strategy-triggered or AI-triggered order placement is in scope for this operating model.
- Personalised investment advisory is **out of scope and disabled** unless a separate legal assessment, registration/approval path and product gate explicitly authorize it.
- AIR must not describe itself as SEBI registered, approved, certified or compliant unless the exact legal entity, registration and permitted activities have been verified and approved for the claim.

The hybrid label does not determine regulatory status. Classification depends on actual activities, product design, customer journey, marketing, compensation, recommendations and execution behavior. A disclaimer cannot cure an activity that requires registration.


## 1A. Internal personal-use technical-analysis mode

AIR must support a clearly separated **Internal / Personal Analysis** workspace for the product owner's own technical analysis and trading decisions.

Permitted product capabilities in this workspace, subject to broker, exchange, data-provider and other applicable rules:
- Charts, indicators, screeners, price/volume/derivatives analytics and option-chain analysis.
- User-authored SMC, ORB, Fibonacci, QOC and other strategy rules.
- Private watchlists, alerts, research notes, simulations, backtests and paper trading.
- Private signal calculations and order-ticket preparation for the user's own account.
- Manual order placement only where the connected broker permits the specific workflow and the applicable algo/API requirements are satisfied.

Boundary conditions:
1. This workspace is for the user's own analysis and decisions. It must not be used to provide research services, recommendations, tips, model portfolios or investment advice to customers or other persons unless the relevant regulatory applicability, registration and controls have been satisfied.
2. Do not distribute internal QOC outputs, security-specific buy/sell/hold calls, strike/entry/stop-loss/target recommendations, screenshots or derived reports to public channels, paid groups, customers or prospective customers as a service without first obtaining a written legal classification. Calling a recommendation "technical analysis", "education", "software output" or adding a disclaimer does not by itself create an exemption.
3. SEBI's February 2026 Research Analyst FAQ clarifies that research services/recommendations on securities are not exempt merely because the methodology is technical analysis; the FAQ distinguishes technical analysis concerning demand and supply for a sector or index. Therefore, AIR must not assume that security-specific technical-analysis recommendations are exempt when shared with others.
4. Keep personal-use data, notes, watchlists and broker credentials private and tenant-isolated. Do not reuse one user's personal data to create recommendations for another.
5. Internal-use mode is not a blanket exemption from insider-trading, market-manipulation, exchange/broker terms, market-data licensing, privacy, tax, FEMA/LRS or retail algo requirements. Personal trading through APIs or automation requires a separate assessment of the exact broker workflow.
6. The user's own account and own analysis must be clearly distinguished from any future AIR research entity's activity. If a regulated research entity/analyst is later established, its employee/analyst personal-trading restrictions, pre-clearance, restricted lists and conflict controls must be assessed and applied; do not assume personal use remains unrestricted.
7. The mode must have a hard access boundary: owner-only role, no customer sharing/export/publication action by default, visible INTERNAL label on generated reports, and an audit record of exports/shares. A future sharing feature must route through the compliance publication workflow.

This mode is a product control intended to keep personal analysis separate from customer-facing research. It is not a legal determination that every possible use is exempt. Obtain counsel confirmation before enabling any external distribution or API-based order flow.

## 2. Regulatory baseline and legal-review requirement

This is an engineering control framework, not a legal opinion. Before launch, Indian securities counsel/compliance professional must prepare and sign a current applicability opinion against the exact AIR legal entity, customer segments, distribution channels, fees, research outputs and broker integrations.

The compliance register must track amendments and circulars, not only the base regulations. Baseline sources to be revalidated at each release:
- SEBI (Research Analysts) Regulations, 2014, as amended; SEBI's regulations listing currently records amendment through 10 October 2026.
- SEBI (Investment Advisers) Regulations, 2013, as amended.
- SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 dated 4 February 2025 on safer participation of retail investors in algorithmic trading, together with subsequent SEBI/exchange implementation standards, operational modalities and extensions/clarifications.
- SEBI Investor Charter and applicable RA/IA investor-charter, complaint-disclosure and grievance requirements.
- Applicable stock-exchange, broker, data-vendor, privacy, cyber-security, record-retention and cross-border rules.

Official starting references:
- SEBI regulations: https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&smid=0-4&ssid=3\n- SEBI Research Analyst FAQ (February 2026), including technical-analysis methodology clarification: https://www.sebi.gov.in/sebi_data/attachdocs/feb-2026/1770375507051.pdf
- SEBI legal framework/circulars: https://www.sebi.gov.in/legal/circulars.html
- SEBI retail algo circular: https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html
- SEBI Investor Charter: https://investor.sebi.gov.in/Investor-charter.html
- NSE empanelled algo providers and current exchange operational references: https://betanseapi.nseindia.com/static/trade/empanelled-algo-providers-exchange

## 3. Feature-by-feature applicability assessment (provisional)

| AIR capability | Provisional regulatory treatment | Product control / launch condition |
|---|---|---|
| General charts, historical data, screeners and user-operated analytics | May be software functionality; classification depends on how it is marketed, configured and monetised | Keep generic tools distinct from AIR-issued recommendations; counsel to confirm boundary |
| User-created backtests and strategy builders | Software tool, but published claims, model portfolios or recommendations may become research/advice | User-defined assumptions; no guaranteed-return claims; preserve reproducibility and limitations |
| AIR QOC LIVE / POSITIONAL / POST-MARKET with ranked instruments, CE/PE, strike, entry, stop-loss and targets | High likelihood of research-service / recommendation analysis requiring RA applicability review; paid or public distribution must be assessed | Do not commercially distribute as AIR research until RA status, personnel, disclosures, policies and client records are approved |
| AIR stock/option watchlists, trade ideas, research reports and public posts | Potential research recommendations / public-media activity | Apply registration-status, conflict, ownership, methodology and other required disclosures; approval workflow before publication |
| Personalised recommendations using a customer's holdings, income, risk profile or goals | Potential IA activity | Disabled in this operating model; separate IA legal opinion, registration and client suitability/risk-profiling controls required before enablement |
| Order ticket prepared from a signal, customer manually reviews and approves | Controlled customer-initiated execution; API/broker terms and exact technical flow still need legal/broker confirmation | No auto-submit, auto-modify, auto-cancel, schedule or strategy-triggered order; explicit customer action per order; immutable approval audit |
| Automated strategy execution, copy trading or unattended order placement | Potential retail algo framework and broker/exchange provider obligations | Out of scope and feature-flagged OFF; separate Gate/approval, broker sponsorship, exchange empanelment/registration and operational acceptance as applicable |
| Broker account connection and read-only portfolio/order data | Broker contract, consent, privacy and security obligations | Read-only scopes by default; minimum permissions; revocation and audit controls |
| US/global instruments and GIFT City receipts | Additional foreign-market, exchange, provider, FEMA/LRS, RBI and cross-border legal questions may arise; not resolved by SEBI review alone | Separate India cross-border legal review and data-licence review before customer-facing research/tradability claims |

This table is an engineering triage, not a final legal determination. In particular, the RA/IA boundary and API/order flow must be confirmed in writing by counsel.

## 4. Mandatory product controls

### 4.1 Research governance (RA applicability gate)
- Record the legal entity providing research, its verified registration status (if required), approved personnel, qualifications/certifications and permitted activity scope.
- Maintain a research approval workflow with analyst/reviewer attribution, dated rationale, source data, methodology, recommendation validity/horizon and change history.
- Store research reports, recommendations, rationale, public appearances, client communications, consents and other records for the applicable statutory period.
- Implement client onboarding/KYC and fee/terms controls where applicable to the registered research service.
- Capture and render required AI-use disclosures for research services; disclose the extent of AI use as required.
- Capture ownership, financial interests, material conflicts, compensation/associate relationships and other required disclosures; enforce restricted lists and personal-trading controls where applicable.
- Ensure recommendations are supported by relevant data and analysis; define ratings, time horizons and benchmarks consistently.
- Do not selectively release research where equal distribution is required.
- Enforce marketing/content review: no guaranteed returns, misleading win rates, cherry-picked backtests, unsupported performance claims or false SEBI-registration claims.

### 4.2 Advisory boundary (IA OFF)
- No customer-specific recommendation generated from personal financial circumstances, holdings, risk profile, income, liabilities or goals under the approved operating model.
- Do not call the software's generic risk settings a customer risk-profiling/advisory service.
- If AIR later provides personalised investment advice, require a separate IA workstream covering registration, qualification/certification, client agreements, risk profiling, suitability, fees, segregation/conflicts, records, AI accountability and investor-charter obligations.
- Feature flags and API authorization must prevent unapproved advisory workflows from being exposed.

### 4.3 Controlled broker execution
- Read-only broker connection is the default.
- For any permitted order ticket, show instrument, side, quantity, product type, price/order type, estimated value, risk warnings and broker account before approval.
- Require an explicit, authenticated customer confirmation for every individual order; confirmation must bind to the exact order payload/hash shown to the customer.
- No automatic order submission after a signal, timer, workflow event, model output, webhook or page refresh.
- No automatic slicing, repricing, modification, cancellation, trailing stop, basket execution or recurring strategy execution in this operating model.
- Apply broker-specific API terms, OAuth/2FA, token vaulting, least privilege, IP restrictions and rate limits where required by the broker.
- Log customer approval, payload, timestamp, user, broker response, order ID, status and subsequent changes. Provide kill switch/revocation and incident controls.
- Counsel and each broker must confirm whether the precise API workflow falls within any algo framework. Manual confirmation must not be treated as a blanket exemption.
- Any later automated execution requires a separate approved scope and relevant broker/exchange empanelment/registration before activation.

### 4.4 AI, model and data governance
- Version every model, prompt/template, feature set, strategy rule, data source and deployment.
- Record model inputs, output, timestamps, confidence/limitations, human reviewer and the final published recommendation where applicable.
- Prevent client-specific data from being reused across tenants or sent to unapproved model providers.
- Enforce confidentiality, integrity, access controls, retention/deletion policy, encryption, incident response and vendor due diligence.
- For IA services if ever enabled, the adviser remains accountable for client-data security/confidentiality/integrity, other information used for advice, AI-generated advice and legal compliance.
- Preserve provenance and licences for exchange, broker, US/global and alternative data; do not redistribute without rights.

### 4.5 Investor protection and disclosures
- Publish accurate product identity, legal entity, service scope, fees, limitations, risks and conflicts.
- Show derivatives/options risk warnings and avoid implying any signal is a guaranteed outcome.
- Provide a clear complaint intake, tracking, escalation and response process.
- Where AIR is a registered RA/IA, implement the applicable Investor Charter, complaint disclosure, SCORES and other prescribed grievance mechanisms and timelines.
- Maintain consent, terms acceptance, communication history and proof of disclosure.
- Provide fair cancellation/termination and customer data-access/deletion processes subject to statutory retention.

### 4.6 Security, privacy and operational controls
- MFA, RBAC, tenant isolation, encrypted secrets/tokens, least privilege, audit logs and security monitoring.
- Separate research entitlements from broker trading permissions.
- Prevent staff or support personnel from placing orders on behalf of customers in this operating model.
- Incident, complaint, data-breach and erroneous-signal response runbooks.
- Independent security testing and periodic access reviews.

## 5. Required compliance evidence register

| Evidence ID | Required evidence | Owner | Release condition |
|---|---|---|---|
| SEBI-01 | Written legal classification of AIR entity, service, fee model, audience and all feature journeys | Indian securities counsel / Compliance Officer | Mandatory before external research launch |
| SEBI-02 | RA registration/applicability determination, approved personnel and operating procedures | AIR legal entity / Compliance Officer | Mandatory before AIR-issued research/recommendations are distributed where registration is required |
| SEBI-03 | IA applicability determination; confirmation personalised advisory is disabled | Counsel / Product | Mandatory before launch; IA enablement requires separate approval |
| SEBI-04 | Broker-by-broker API permission matrix and written confirmation of controlled-order flow | Broker owner / Counsel | Mandatory before order-ticket API activation |
| SEBI-05 | Written algo-framework applicability review; automated execution feature flags OFF | Counsel / Engineering | Mandatory before broker API release |
| SEBI-06 | Research disclosure, conflicts, ownership, AI-use disclosure and content approval templates | Compliance / Research | Mandatory before research distribution |
| SEBI-07 | Client onboarding, terms, consent, fee and record-retention schedule | Compliance / Product | Mandatory before paid research onboarding |
| SEBI-08 | Investor Charter, complaint process, monthly disclosures and SCORES workflow where applicable | Compliance / Support | Mandatory before registered-service launch |
| SEBI-09 | AI/model governance, source-data lineage and reproducibility evidence | Engineering / Research | Mandatory before AI-assisted research launch |
| SEBI-10 | Privacy/security assessment, penetration test and broker-token security review | Security | Mandatory before production |
| SEBI-11 | Exchange/data-provider licence matrix including display, storage, derived data and redistribution rights | Data owner / Legal | Mandatory before market-data publication |
| SEBI-12 | US/GIFT City cross-border legal opinion (SEBI, RBI/FEMA/LRS, venue and provider obligations) | Indian and relevant foreign counsel | Mandatory before those services are commercially offered |
| SEBI-13 | Final signed compliance opinion and release authorization | Compliance Officer + external counsel | Mandatory Gate 17E exit |

## 6. Release-blocking policy

- Gate 17E is a mandatory release gate **after Gate 17D and before Gate 18 final release certification**. Compliance design and evidence preparation may proceed in parallel with Gates 17B–17D.
- No public/paid AIR research recommendation feature may be enabled until SEBI-01, SEBI-02 and relevant disclosure/records/investor-protection evidence are approved.
- Personalised advisory remains disabled unless a separately approved IA gate is completed.
- Automated execution remains disabled. Any change from controlled/manual approval requires a new approved gate and broker/exchange evidence.
- No production release may claim "SEBI compliant", "SEBI approved" or "SEBI certified" based solely on passing software tests or this framework.
- Compliance evidence must be reviewed against the regulations/circulars in force on the release date. Regulatory changes trigger impact analysis, owner assignment, remediation and regression tests.
- If legal applicability is uncertain, default to disabling the affected feature until written counsel approval.

## 7. Sources and update discipline

Official sources reviewed for this programme baseline:
- SEBI regulations listing (RA Regulations last amended 10 October 2026; IA Regulations last amended 25 November 2025): https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&smid=0-4&ssid=3
- SEBI Research Analysts (Amendment) Regulations, 2026 notification: https://www.sebi.gov.in/web/?file=https%3A%2F%2Fwww.sebi.gov.in%2Fsebi_data%2Fattachdocs%2Foct-2026%2F1791796596784.pdf
- SEBI retail algorithmic trading circular, 4 February 2025: https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html
- SEBI RA regulations consolidated text / AI-use disclosure and records provisions: https://www.sebi.gov.in/web/?file=https%3A%2F%2Fwww.sebi.gov.in%2Fsebi_data%2Fattachdocs%2Ffeb-2025%2F1740726945457.pdf
- SEBI IA regulations text / AI accountability and risk-profiling provisions: https://www.sebi.gov.in/sebi_data/attachdocs/aug-2025/1755176446980.pdf
- SEBI Investor Charter: https://investor.sebi.gov.in/Investor-charter.html
- SEBI RA FAQs: https://www.sebi.gov.in/web/?file=https%3A%2F%2Fwww.sebi.gov.in%2Fsebi_data%2Fattachdocs%2Fjul-2025%2F1753268710217.pdf
- NSE empanelled algo provider page and current operational references: https://betanseapi.nseindia.com/static/trade/empanelled-algo-providers-exchange

This source list is not exhaustive. Compliance owner must verify later amendments, circulars, exchange notices, RBI/FEMA and foreign-market requirements before each relevant release.

## 8. Internal-use mode acceptance criteria

- Owner-only internal workspace exists and is not exposed to customer tenants.
- All internally generated reports/signals are visibly marked INTERNAL / NOT FOR DISTRIBUTION.
- External sharing, public posting, client delivery and paid distribution are disabled unless routed through the approved research compliance workflow.
- No customer-specific advice workflow is exposed in internal-use mode.
- Broker integration defaults to read-only; any order ticket requires explicit customer action and broker/API/legal permission.
- No automated order submission, modification, cancellation or strategy execution.
- Data licences permit the intended personal/internal use.
- Counsel confirms the intended internal-use and personal trading workflow before production release.
