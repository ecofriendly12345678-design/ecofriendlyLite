"""Order-book-aware fill simulation. Walk real ask depth level by level so the
paper P&L reflects what a real taker order would actually pay."""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from agent.models import BookLevel, Fill, OrderBook, ResultSet, SetPurchase

_GRAIN = Decimal("0.01")  # share-quantity granularity


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


def plan_set_purchase(
    result_set: ResultSet,
    books: dict[str, OrderBook],
    max_cost_per_set: Decimal,
    max_notional: Decimal,
) -> SetPurchase | None:
    """Largest feasible n_sets (0.01-share granularity) with
    total cost <= max_notional and cost per set <= max_cost_per_set.

    Both constraints are monotone in qty: total cost strictly increases, and
    average cost per set is non-decreasing because ask levels are walked
    cheapest-first. The feasible region is therefore a prefix (0, q_max], and
    we find q_max by bisection on the 0.01 grid. Deterministic,
    O(levels * log(depth / 0.01))."""
    legs: list[tuple[str, str, list[BookLevel]]] = []
    for outcome in result_set.outcomes:
        book = books.get(outcome.token_id)
        if book is None or not book.asks:
            return None
        legs.append((outcome.token_id, outcome.label, book.asks))

    def evaluate(qty: Decimal) -> list[tuple[str, str, Decimal]] | None:
        """Leg costs at qty, or None if any constraint fails."""
        leg_costs: list[tuple[str, str, Decimal]] = []
        for tid, label, asks in legs:
            cost = walk_book(asks, qty)
            if cost is None:
                return None
            leg_costs.append((tid, label, cost))
        total = sum(c for _, _, c in leg_costs)
        if total > max_notional or total / qty > max_cost_per_set:
            return None
        return leg_costs

    # Upper bound in grid units: depth of the thinnest leg, further capped by
    # the notional at best-ask prices (cost(q) >= q * best_ask_sum).
    min_depth = min(sum(l.size for l in asks) for _, _, asks in legs)
    best_ask_sum = sum(asks[0].price for _, _, asks in legs)
    hi_qty = min_depth
    if best_ask_sum > 0:
        hi_qty = min(hi_qty, max_notional / best_ask_sum)
    hi = int((hi_qty / _GRAIN).to_integral_value(rounding=ROUND_DOWN))
    if hi < 1 or evaluate(_GRAIN) is None:
        return None  # monotone => nothing feasible anywhere

    lo = 1  # units of _GRAIN; known feasible
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if evaluate(mid * _GRAIN) is not None:
            lo = mid
        else:
            hi = mid - 1

    qty = lo * _GRAIN
    leg_costs = evaluate(qty)
    assert leg_costs is not None  # lo is feasible by invariant
    total = sum(c for _, _, c in leg_costs)
    fills = tuple(
        Fill(token_id=tid, label=label, qty=qty, avg_price=cost / qty, cost=cost)
        for tid, label, cost in leg_costs
    )
    return SetPurchase(result_set=result_set, n_sets=qty, fills=fills, total_cost=total)
