import asyncio
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from app.brokers.base import OrderRequest, BrokerOrder
from app.brokers.registry import BrokerRegistry
from app.brokers.customer_accounts import CustomerAccountDirectory
from app.services.order_ledger import DurableOrderLedger


@dataclass(frozen=True)
class ExecutionPolicy:
    live_enabled: bool = False
    max_order_value: Decimal = Decimal("0")
    max_quantity: int = 0


@dataclass(frozen=True)
class AccountOrderResult:
    broker: str
    account_id: str
    status: str
    broker_order_id: str | None = None
    error: str | None = None


class ExecutionService:
    """Guarded single-account and one-click multi-account order routing."""

    def __init__(
        self,
        registry: BrokerRegistry,
        policies: dict[tuple[str, str], ExecutionPolicy],
        account_directory: CustomerAccountDirectory,
        ledger: DurableOrderLedger | None = None,
    ) -> None:
        self.registry = registry
        self.policies = policies
        self.account_directory = account_directory
        self.ledger = ledger
        self._idempotency: dict[tuple[str, str, str], BrokerOrder] = {}

    def _validate(
        self,
        broker: str,
        order: OrderRequest,
        *,
        paper: bool,
        estimated_order_value: Decimal | None,
    ) -> None:
        if order.quantity <= 0:
            raise ValueError("Quantity must be positive")
        if not order.idempotency_key.strip():
            raise ValueError("An idempotency key is required")
        if order.side.upper() not in {"BUY", "SELL"}:
            raise ValueError("Side must be BUY or SELL")
        if order.order_type.upper() not in {"MARKET", "LIMIT", "SL", "SL-M"}:
            raise ValueError("Unsupported order type")
        if not paper:
            policy = self.policies.get((broker, order.account_id), ExecutionPolicy())
            if not policy.live_enabled:
                raise PermissionError(f"Live execution is disabled for {broker}/{order.account_id}")
            if policy.max_quantity <= 0 or order.quantity > policy.max_quantity:
                raise ValueError(f"Quantity exceeds live risk limit for {broker}/{order.account_id}")
            if estimated_order_value is None or policy.max_order_value <= 0:
                raise ValueError(f"Order value or max value missing for {broker}/{order.account_id}")
            if estimated_order_value > policy.max_order_value:
                raise ValueError(f"Order value exceeds live risk limit for {broker}/{order.account_id}")
            if order.order_type.upper() == "LIMIT" and (order.price is None or order.price <= 0):
                raise ValueError("A valid positive limit price is required")
            if order.order_type.upper() == "MARKET" and order.price is not None:
                raise ValueError("Market orders must not carry a limit price")

    async def submit(
        self,
        broker_code: str,
        order: OrderRequest,
        *,
        customer_id: str,
        confirmed_by_user: bool,
        paper: bool = True,
        estimated_order_value: Decimal | None = None,
    ) -> BrokerOrder:
        broker = broker_code.strip().lower()
        account = order.account_id.strip()
        if not broker or not account:
            raise ValueError("Broker and account identifiers are required")
        if not confirmed_by_user:
            raise PermissionError("Explicit user confirmation is required")
        self.account_directory.authorize_order_target(customer_id, broker, account)
        self._validate(broker, order, paper=paper, estimated_order_value=estimated_order_value)
        key = (broker, account, order.idempotency_key)
        if self.ledger is not None:
            persisted = self.ledger.get(broker, account, order.idempotency_key)
            if persisted is not None:
                if persisted.status in {"PENDING", "UNKNOWN"}:
                    raise RuntimeError(
                        f"Order intent is {persisted.status}; reconcile with broker before any retry"
                    )
                return persisted
            reserved = self.ledger.reserve(
                broker, account, order.idempotency_key,
                intent={
                    "symbol": order.symbol, "token": order.token,
                    "side": order.side, "order_type": order.order_type,
                    "quantity": order.quantity, "product": order.product,
                    "price": str(order.price) if order.price is not None else None,
                    "paper": paper,
                },
            )
            if not reserved:
                existing = self.ledger.get(broker, account, order.idempotency_key)
                if existing is None or existing.status in {"PENDING", "UNKNOWN"}:
                    raise RuntimeError("Order intent already reserved; reconcile before retry")
                return existing
        if key in self._idempotency:
            return self._idempotency[key]
        try:
            if paper:
                result = BrokerOrder(
                    broker=broker, account_id=account,
                    broker_order_id=f"PAPER-{account}-{order.idempotency_key}",
                    status="PAPER_ACCEPTED",
                    raw={"mode": "paper", "not_sent_to_broker": True},
                )
            else:
                result = await self.registry.get(broker, account).place_order(order)
        except Exception as exc:
            if self.ledger is not None:
                self.ledger.record(BrokerOrder(
                    broker=broker, account_id=account, broker_order_id="",
                    status="UNKNOWN",
                    raw={"submission_outcome": "unknown", "error_type": type(exc).__name__,
                         "message": str(exc)[:500], "reconcile_before_retry": True},
                ), order.idempotency_key)
            raise
        self._idempotency[key] = result
        if self.ledger is not None:
            self.ledger.record(result, order.idempotency_key)
        return result

    async def submit_to_active_accounts(
        self,
        orders: dict[tuple[str, str], OrderRequest],
        *,
        customer_id: str,
        confirmed_by_user: bool,
        paper: bool = True,
        estimated_values: dict[tuple[str, str], Decimal] | None = None,
    ) -> list[AccountOrderResult]:
        """Fan out one reviewed intent to selected active accounts.

        The caller supplies an explicit per-account order map, so quantity and
        instrument can differ by account. All accounts are preflighted before
        the first live request. Broker responses can still partially succeed;
        callers must reconcile every returned result and broker order book.
        """
        if not confirmed_by_user:
            raise PermissionError("One explicit confirmation is required before multi-account execution")
        if not orders:
            raise ValueError("Select at least one account")
        active = {
            (row["broker"], row["account_id"])
            for row in self.registry.active_accounts()
        }
        targets = list(orders.items())
        if len({key for key, _ in targets}) != len(targets):
            raise ValueError("Duplicate broker account target")
        values = estimated_values or {}

        # Complete preflight before submitting to any account.
        for (broker_code, account_id), order in targets:
            broker, account = broker_code.strip().lower(), account_id.strip()
            if (broker, account) not in active:
                raise PermissionError(f"Account is not active: {broker}/{account}")
            if order.account_id != account:
                raise ValueError(f"Order account_id mismatch for {broker}/{account}")
            self.account_directory.authorize_order_target(customer_id, broker, account)
            self.registry.get(broker, account)
            self._validate(
                broker, order, paper=paper,
                estimated_order_value=values.get((broker, account)),
            )

        async def dispatch(broker: str, account: str, order: OrderRequest) -> AccountOrderResult:
            try:
                # Namespace the idempotency key per destination account.
                routed = replace(
                    order,
                    idempotency_key=f"{order.idempotency_key}:{broker}:{account}",
                )
                result = await self.submit(
                    broker, routed, customer_id=customer_id, confirmed_by_user=True, paper=paper,
                    estimated_order_value=values.get((broker, account)),
                )
                return AccountOrderResult(
                    broker, account, result.status, result.broker_order_id
                )
            except Exception as exc:
                return AccountOrderResult(
                    broker, account, "FAILED", error=str(exc)
                )

        return list(await asyncio.gather(
            *(dispatch(b.strip().lower(), a.strip(), o) for (b, a), o in targets)
        ))
