import json
from decimal import Decimal

from agent.models import OrderBook
from agent.scanner import (
    find_opportunities,
    result_set_from_event,
    result_set_from_market,
)


def market_json(cond="0xcond1", yes="101", no="102", active=True, closed=False):
    return {
        "conditionId": cond,
        "question": "Will it happen?",
        "slug": "will-it-happen",
        "active": active,
        "closed": closed,
        "enableOrderBook": True,
        "clobTokenIds": json.dumps([yes, no]),
        "outcomes": json.dumps(["Yes", "No"]),
    }


def book(token, best_ask, best_bid, depth="1000"):
    return OrderBook.from_json({
        "asset_id": token,
        "asks": [{"price": best_ask, "size": depth}],
        "bids": [{"price": best_bid, "size": depth}],
    })


def test_result_set_from_market_binary():
    rs = result_set_from_market(market_json())
    assert rs is not None
    assert rs.kind == "binary"
    assert rs.set_id == "0xcond1"
    assert [o.label for o in rs.outcomes] == ["Yes", "No"]
    assert rs.token_ids == ["101", "102"]


def test_result_set_from_market_hex_tokens_normalized():
    rs = result_set_from_market(market_json(yes="0xff", no="0x100"))
    assert rs.token_ids == ["255", "256"]


def test_result_set_from_market_rejects_closed():
    assert result_set_from_market(market_json(closed=True)) is None
    assert result_set_from_market(market_json(active=False)) is None


def test_result_set_from_event_neg_risk():
    ev = {
        "id": "500", "title": "Who wins?", "negRisk": True,
        "markets": [
            {**market_json(cond="0xc1", yes="201", no="202"), "groupItemTitle": "Alice"},
            {**market_json(cond="0xc2", yes="203", no="204"), "groupItemTitle": "Bob"},
            {**market_json(cond="0xc3", yes="205", no="206"), "groupItemTitle": "Carol"},
        ],
    }
    rs = result_set_from_event(ev)
    assert rs is not None
    assert rs.kind == "neg_risk_event"
    assert rs.set_id == "event:500"
    # one outcome per market, YES token only
    assert rs.token_ids == ["201", "203", "205"]
    assert [o.label for o in rs.outcomes] == ["Alice", "Bob", "Carol"]


def test_result_set_from_event_rejects_non_negrisk():
    assert result_set_from_event({"id": "1", "negRisk": False, "markets": []}) is None


def test_find_opportunity_cheap_set_flagged():
    rs = result_set_from_market(market_json())
    books = {"101": book("101", "0.55", "0.53"), "102": book("102", "0.42", "0.40")}
    opps = find_opportunities([rs], books, Decimal("0.01"), Decimal("0"), Decimal("0.95"))
    assert len(opps) == 1
    assert opps[0].cost == Decimal("0.97")
    assert opps[0].edge == Decimal("0.03")


def test_find_opportunity_fair_set_ignored():
    rs = result_set_from_market(market_json())
    books = {"101": book("101", "0.55", "0.53"), "102": book("102", "0.45", "0.44")}
    opps = find_opportunities([rs], books, Decimal("0.01"), Decimal("0"), Decimal("0.95"))
    assert opps == []


def test_find_opportunity_three_outcome_event():
    ev = {
        "id": "500", "title": "Who wins?", "negRisk": True,
        "markets": [
            {**market_json(cond="0xc1", yes="201", no="202"), "groupItemTitle": "A"},
            {**market_json(cond="0xc2", yes="203", no="204"), "groupItemTitle": "B"},
            {**market_json(cond="0xc3", yes="205", no="206"), "groupItemTitle": "C"},
        ],
    }
    rs = result_set_from_event(ev)
    books = {
        "201": book("201", "0.30", "0.29"),
        "203": book("203", "0.30", "0.29"),
        "205": book("205", "0.35", "0.34"),
    }
    opps = find_opportunities([rs], books, Decimal("0.01"), Decimal("0"), Decimal("0.90"))
    assert len(opps) == 1
    assert opps[0].cost == Decimal("0.95")


def test_find_opportunity_fee_eats_edge():
    rs = result_set_from_market(market_json())
    books = {"101": book("101", "0.55", "0.53"), "102": book("102", "0.42", "0.40")}
    # edge 0.03 but min_edge 0.02 + fee 0.02 = 0.04 threshold -> no opp
    opps = find_opportunities([rs], books, Decimal("0.02"), Decimal("0.02"), Decimal("0.95"))
    assert opps == []


def test_find_opportunity_missing_book_skipped():
    rs = result_set_from_market(market_json())
    books = {"101": book("101", "0.55", "0.53")}  # 102 missing
    assert find_opportunities([rs], books, Decimal("0.01"), Decimal("0"), Decimal("0.95")) == []


def test_sanity_guard_rejects_low_mid_sum():
    # mids sum to 0.55+0.10=0.65 < 0.95 -> likely non-exhaustive, skip even though asks sum < 1
    rs = result_set_from_market(market_json())
    books = {"101": book("101", "0.56", "0.54"), "102": book("102", "0.11", "0.09")}
    assert find_opportunities([rs], books, Decimal("0.01"), Decimal("0"), Decimal("0.95")) == []
