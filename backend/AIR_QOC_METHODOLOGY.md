# AIR QOC — Qualified Options Confluence

## Purpose

AIR QOC is an evidence filter over normalized, account-scoped broker option-chain snapshots. It is a research workflow, not an execution engine. It does not place, modify, or cancel orders.

## Data requirement

A contract is never scored as a signal from a single observation. Qualification compares the two latest distinct observations for the same provider, account, underlying, expiry, strike and CE/PE side. Both observations must be from the current IST session. The latest observation must satisfy the selected workflow freshness window:

| Workflow | Maximum age | Intended use |
|---|---:|---|
| LIVE | 5 minutes | Intraday qualification from current session snapshots |
| POSITIONAL | 30 minutes | Late-session review; a fresh snapshot is still required |
| POST_MARKET | 24 hours, same IST session | Completed-session research; not an intraday entry trigger |

The scheduler currently captures selected-provider option-chain snapshots at 15:20 IST on weekdays when explicitly enabled. Manual chain retrieval also stores snapshots. The scheduler being enabled is not proof that a live intraday feed or full-session sampling is configured.

## Required gates

1. Two distinct observations exist for the same contract.
2. Latest observation is fresh and belongs to the current IST session.
3. Underlying movement confirms direction: CE with at least +0.05%; PE with at least -0.05% between snapshots.
4. Option premium increases by at least 2% between snapshots.
5. Contract volume increases between snapshots.
6. Open interest increases between snapshots.
7. Two-sided bid/ask quotes have positive quantities and spread no wider than 5% of midpoint.
8. Contract is OTM by 0.05% to 5% relative to the underlying.
9. Expiry is valid and not expired.

Any failed gate forces REJECT, even if the numeric score would otherwise be high.

## Score

| Evidence | Maximum | Scoring |
|---|---:|---|
| Underlying directional move | 20 | 10 / 15 / 20 as aligned move strengthens |
| Option premium acceleration | 20 | 10 / 15 / 20 for +2% / +5% / +10% |
| Volume increase | 15 | 5 / 10 / 15 for positive / +100 / +500 contracts |
| OI increase | 15 | 5 / 10 / 15 for positive / +100 / +500 contracts |
| Bid/ask liquidity | 15 | 5 / 10 / 15 for spread up to 5% / 3% / 1.5% |
| OTM distance | 10 | 5 for edge band; 10 for 0.1–3% |
| Freshness | 5 | Current-session observation within mode window |

| Score | Classification |
|---:|---|
| 90–100 | HIGH_CONVICTION |
| 80–89 | QUALIFIED |
| 70–79 | WATCH |
| Below 70 | REJECT |

The output includes the component breakdown, failed gates, underlying and premium changes, volume/OI deltas, OTM distance, spread, source timestamp and DTE. The endpoint reports counts over the full evaluated set and returns the top-ranked candidates (up to 100).

## Risk and execution

The UI displays an illustrative 30% premium stop reference and +50%, +100%, +200% and +300% premium milestones. These are arithmetic reference levels, not backtested expectancy, advice, guaranteed targets or automatic exits. Every decision remains manual. No order-placement API is called by this workflow.

## Known limitations

- Current customer UI and qualification endpoint use the operator-authorized Dhan account snapshot store. Other broker adapters may capture snapshots, but cross-provider QOC selection is not yet surfaced in this screen.
- The current automated scheduler is an EOD 15:20 IST capture, not a substitute for frequent live snapshots. LIVE mode returns rejects/no qualified results when fresh repeated intraday snapshots are absent.
- Scores are deterministic rule scores, not calibrated probabilities. No historical performance claim is made until a separate, point-in-time backtest with transaction costs, slippage and survivorship controls is complete.
- A 24-hour POST_MARKET freshness window is still restricted to the same IST calendar session.
