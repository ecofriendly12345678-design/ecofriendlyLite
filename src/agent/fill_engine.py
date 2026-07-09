"""Pure order-book fill simulation for local paper execution."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from agent.models import BookLevel, OrderBook, ResultSet


@dataclass(frozen=True)
class SimulatedFill:
    token_id: str
    label: str
    qty: Decimal
    avg_price: Decimal
    amount: Decimal


def _walk_levels(levels: Iterable[BookLevel], qty: Decimal) -> Decimal | None:
    if qty <= 0:
        return None
    remaining = qty
    amount = Decimal("0")
    for level in levels:
        take = min(remaining, level.size)
        amount += take * level.price
        remaining -= take
        if remaining == 0:
            return amount
    return None


def simulate_buy_leg(book: OrderBook, label: str, qty: Decimal) -> SimulatedFill | None:
    amount = _walk_levels(book.asks, qty)
    if amount is None:
        return None
    return SimulatedFill(
        token_id=book.token_id,
        label=label,
        qty=qty,
        avg_price=amount / qty,
        amount=amount,
    )


def simulate_sell_leg(book: OrderBook, label: str, qty: Decimal) -> SimulatedFill | None:
    amount = _walk_levels(book.bids, qty)
    if amount is None:
        return None
    return SimulatedFill(
        token_id=book.token_id,
        label=label,
        qty=qty,
        avg_price=amount / qty,
        amount=amount,
    )


def simulate_basket_buy(
    result_set: ResultSet,
    books: dict[str, OrderBook],
    qty: Decimal,
) -> tuple[SimulatedFill, ...] | None:
    fills: list[SimulatedFill] = []
    for outcome in result_set.outcomes:
        book = books.get(outcome.token_id)
        if book is None:
            return None
        fill = simulate_buy_leg(book, outcome.label, qty)
        if fill is None:
            return None
        fills.append(fill)
    return tuple(fills)
