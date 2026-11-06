from dataclasses import dataclass
from decimal import Decimal

from app.brokers.base import OrderRequest, BrokerOrder
from app.brokers.registry import BrokerRegistry


@dataclass(frozen=True)
class ExecutionPolicy:
    live_enabled: bool = False
    max_order_value: Decimal = Decimal("0")
    max_quantity: int = 0


class ExecutionService:
    """Single guarded route; risk policy and idempotency are isolated per account."""

    def __init__(
        self,
        registry: BrokerRegistry,
        policies: dict[tuple[str, str], ExecutionPolicy],
    ) -> None:
        self.registry = registry
        self.policies = policies
        self._idempotency: dict[tuple[str, str, str], BrokerOrder] = {}

    async def submit(
        self,
        broker_code: str,
        order: OrderRequest,
        *,
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
        if order.quantity <= 0:
            raise ValueError("Quantity must be positive")
        if not order.idempotency_key.strip():
            raise ValueError("An idempotency key is required")

        key = (broker, account, order.idempotency_key)
        if key in self._idempotency:
            return self._idempotency[key]

        policy = self.policies.get((broker, account), ExecutionPolicy())
        if not paper:
            if not policy.live_enabled:
                raise PermissionError("Live execution is disabled for this broker account")
            if policy.max_quantity <= 0 or order.quantity > policy.max_quantity:
                raise ValueError("Order quantity exceeds configured live risk limit")
            if estimated_order_value is None or policy.max_order_value <= 0:
                raise ValueError("Live order value and a configured maximum are required")
            if estimated_order_value > policy.max_order_value:
                raise ValueError("Order value exceeds configured live risk limit")
            if order.order_type.upper() == "MARKET" and order.price is not None:
                raise ValueError("Market orders must not carry a limit price")
            if order.order_type.upper() == "LIMIT" and (order.price is None or order.price <= 0):
                raise ValueError("A valid positive limit price is required")

        if paper:
            result = BrokerOrder(
                broker=broker,
                account_id=account,
                broker_order_id=f"PAPER-{account}-{order.idempotency_key}",
                status="PAPER_ACCEPTED",
                raw={"mode": "paper", "not_sent_to_broker": True},
            )
        else:
            result = await self.registry.get(broker, account).place_order(order)

        self._idempotency[key] = result
        return result
