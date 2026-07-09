"""Arb signal: a complete set of mutually exclusive outcomes pays exactly $1.
If the sum of best asks for the full set is < $1 - threshold - fee, buying
the set locks a profit. Pure logic over parsed data; no I/O here."""
from __future__ import annotations

import json
from decimal import Decimal

from agent.models import Opportunity, OrderBook, Outcome, ResultSet, normalize_token_id

ONE = Decimal("1")


def _json_list(raw: object) -> list:
    """Gamma encodes list fields as JSON strings, e.g. '["Yes","No"]'."""
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, list):
        return raw
    return []


def _tradeable(market: dict) -> bool:
    return (
        market.get("active") is True
        and market.get("closed") is not True
        and market.get("enableOrderBook") is not False
    )


def result_set_from_market(market: dict) -> ResultSet | None:
    if not _tradeable(market):
        return None
    try:
        tokens = [normalize_token_id(t) for t in _json_list(market.get("clobTokenIds"))]
    except (ValueError, json.JSONDecodeError):
        return None
    labels = _json_list(market.get("outcomes"))
    if len(tokens) != 2 or len(labels) != 2:
        return None
    cond = market.get("conditionId")
    if not cond:
        return None
    return ResultSet(
        set_id=str(cond),
        description=str(market.get("question") or market.get("slug") or cond),
        kind="binary",
        outcomes=tuple(Outcome(t, str(l)) for t, l in zip(tokens, labels)),
    )


def result_set_from_event(event: dict) -> ResultSet | None:
    """Neg-risk event -> one set of every member market's YES token.

    Caveat (why the sanity guard exists): buying every listed outcome pays $1
    only if the listed outcomes are exhaustive. Mutual exclusivity is
    guaranteed by neg-risk mechanics; exhaustiveness is not (candidates can
    be added). find_opportunities() therefore also requires Σ midpoints to be
    close to $1 before trusting a cheap-set signal."""
    if event.get("negRisk") is not True:
        return None
    outcomes: list[Outcome] = []
    for market in event.get("markets") or []:
        if not _tradeable(market):
            continue
        try:
            tokens = [normalize_token_id(t) for t in _json_list(market.get("clobTokenIds"))]
        except (ValueError, json.JSONDecodeError):
            continue
        if not tokens:
            continue
        label = str(market.get("groupItemTitle") or market.get("question") or tokens[0])
        outcomes.append(Outcome(tokens[0], label))  # first token = YES
    if len(outcomes) < 2:
        return None
    return ResultSet(
        set_id=f"event:{event.get('id')}",
        description=str(event.get("title") or event.get("slug") or event.get("id")),
        kind="neg_risk_event",
        outcomes=tuple(outcomes),
    )


def find_opportunities(
    sets: list[ResultSet],
    books: dict[str, OrderBook],
    min_edge: Decimal,
    est_fee: Decimal,
    sanity_min_mid_sum: Decimal,
) -> list[Opportunity]:
    opps: list[Opportunity] = []
    for rs in sets:
        asks: dict[str, Decimal] = {}
        mid_sum = Decimal("0")
        complete = True
        for tid in rs.token_ids:
            book = books.get(tid)
            if book is None or book.best_ask is None or book.midpoint is None:
                complete = False
                break
            asks[tid] = book.best_ask.price
            mid_sum += book.midpoint
        if not complete:
            continue
        if mid_sum < sanity_min_mid_sum:
            continue  # set priced far below $1 -> likely non-exhaustive, not an arb
        cost = sum(asks.values(), Decimal("0"))
        edge = ONE - cost
        if edge > min_edge + est_fee:
            opps.append(Opportunity(result_set=rs, asks=asks, cost=cost, edge=edge))
    return opps
