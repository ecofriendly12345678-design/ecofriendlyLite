"""Order-book-aware fill simulation. Walk real ask depth level by level so the
paper P&L reflects what a real taker order would actually pay."""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from agent.models import BookLevel, Fill, OrderBook, ResultSet, SetPurchase


def walk_book(asks: list[BookLevel], qty: Decimal) -> Decimal | None:
    """Total cost to buy `qty` shares walking best-first asks. None if depth < qty."""
    if qty <= 0:
        return None
    remaining = qty
    cost = Decimal("0")
    for level in asks:
        take = min(remaining, level.size)
        cost += take * level.price
        remaining -= take
        if remaining == 0:
            return cost
    return None  # insufficient depth


def _breakpoints(asks: list[BookLevel]) -> list[Decimal]:
    """Cumulative-depth breakpoints of one ask book."""
    out, cum = [], Decimal("0")
    for level in asks:
        cum += level.size
        out.append(cum)
    return out


def plan_set_purchase(
    result_set: ResultSet,
    books: dict[str, OrderBook],
    max_cost_per_set: Decimal,
    max_notional: Decimal,
) -> SetPurchase | None:
    """Largest feasible n_sets with total cost <= max_notional and
    cost per set <= max_cost_per_set. Candidates are every leg's depth
    breakpoints plus the notional-capped quantity; first feasible
    (descending) wins. Deterministic and O(levels^2), fine for CLOB books."""
    legs: list[tuple[str, str, list[BookLevel]]] = []
    for outcome in result_set.outcomes:
        book = books.get(outcome.token_id)
        if book is None or not book.asks:
            return None
        legs.append((outcome.token_id, outcome.label, book.asks))

    candidates: set[Decimal] = set()
    for _, _, asks in legs:
        candidates.update(_breakpoints(asks))
    best_ask_sum = sum(asks[0].price for _, _, asks in legs)
    if best_ask_sum > 0:
        # Notional-capped qty at best prices. Floor to 0.01 shares so the
        # inexact division can never round up past the notional cap.
        capped = (max_notional / best_ask_sum).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        candidates.add(capped)

    for qty in sorted(candidates, reverse=True):
        if qty <= 0:
            continue
        leg_costs: list[tuple[str, str, Decimal]] = []
        feasible = True
        for tid, label, asks in legs:
            cost = walk_book(asks, qty)
            if cost is None:
                feasible = False
                break
            leg_costs.append((tid, label, cost))
        if not feasible:
            continue
        total = sum(c for _, _, c in leg_costs)
        if total > max_notional:
            continue
        if total / qty > max_cost_per_set:
            continue
        fills = tuple(
            Fill(token_id=tid, label=label, qty=qty, avg_price=cost / qty, cost=cost)
            for tid, label, cost in leg_costs
        )
        return SetPurchase(
            result_set=result_set, n_sets=qty, fills=fills, total_cost=total
        )
    return None
