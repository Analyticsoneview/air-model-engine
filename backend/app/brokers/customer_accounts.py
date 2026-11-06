"""Customer trading accounts are independent of the single market-data Main Account.

A customer may have one or more authorized accounts with the same broker.
The composite (broker, account_id) is the execution routing key; the
customer_id is used for tenant ownership and must be checked by the API layer.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CustomerTradingAccount:
    customer_id: str
    broker: str
    account_id: str
    enabled_for_orders: bool = False

    def __post_init__(self):
        if not self.customer_id.strip() or not self.broker.strip() or not self.account_id.strip():
            raise ValueError("Customer, broker and account identifiers are required")


class CustomerAccountDirectory:
    """In-memory account metadata only; never store broker secrets here."""

    def __init__(self):
        self._accounts: dict[tuple[str, str], CustomerTradingAccount] = {}

    def add(self, account: CustomerTradingAccount) -> None:
        key = (account.broker.strip().lower(), account.account_id.strip())
        if key in self._accounts:
            raise ValueError("Broker account already assigned to a customer")
        self._accounts[key] = account

    def list_for_customer(self, customer_id: str) -> list[CustomerTradingAccount]:
        return sorted(
            (a for a in self._accounts.values() if a.customer_id == customer_id),
            key=lambda a: (a.broker, a.account_id),
        )

    def authorize_order_target(self, customer_id: str, broker: str, account_id: str) -> None:
        key = (broker.strip().lower(), account_id.strip())
        account = self._accounts.get(key)
        if account is None or account.customer_id != customer_id:
            raise PermissionError("Customer does not own this broker account")
        if not account.enabled_for_orders:
            raise PermissionError("Order placement is disabled for this customer account")
