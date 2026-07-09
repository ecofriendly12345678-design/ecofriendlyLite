from decimal import Decimal

from agent.models import (
    BookLevel,
    Fill,
    Opportunity,
    OrderBook,
    Outcome,
    ResultSet,
    SetPurchase,
    normalize_token_id,
)


def test_normalize_token_id_decimal_passthrough():
    assert normalize_token_id("12345") == "12345"


def test_normalize_token_id_hex_to_decimal():
    assert normalize_token_id("0xff") == "255"
    assert normalize_token_id("0xFF") == "255"


def test_normalize_token_id_real_hex():
    raw = "0xd8b6c36e23f1e9363cbee5692794deb1faa3a8e95fa3255f01d53fbb68c68b43"
    out = normalize_token_id(raw)
    assert out == str(int(raw, 16))


def test_normalize_token_id_garbage_raises():
    import pytest
    with pytest.raises(ValueError):
        normalize_token_id("not-a-token")


def _sample_book_json():
    # Mirrors live CLI output: asks DESCENDING (best last), bids ASCENDING (best last)
    return {
        "market": "0xabc",
        "asset_id": "255",
        "asks": [
            {"price": "0.99", "size": "100"},
            {"price": "0.60", "size": "50"},
            {"price": "0.55", "size": "10"},
        ],
        "bids": [
            {"price": "0.01", "size": "200"},
            {"price": "0.50", "size": "20"},
        ],
    }


def test_orderbook_from_json_sorts_best_first():
    book = OrderBook.from_json(_sample_book_json())
    assert book.token_id == "255"
    assert book.asks[0] == BookLevel(Decimal("0.55"), Decimal("10"))
    assert book.bids[0] == BookLevel(Decimal("0.50"), Decimal("20"))


def test_orderbook_best_and_midpoint():
    book = OrderBook.from_json(_sample_book_json())
    assert book.best_ask.price == Decimal("0.55")
    assert book.best_bid.price == Decimal("0.50")
    assert book.midpoint == Decimal("0.525")


def test_orderbook_empty_side_midpoint_none():
    data = _sample_book_json()
    data["bids"] = []
    book = OrderBook.from_json(data)
    assert book.best_bid is None
    assert book.midpoint is None


def test_orderbook_from_json_hex_asset_id():
    data = _sample_book_json()
    data["asset_id"] = "0xff"
    assert OrderBook.from_json(data).token_id == "255"


def test_result_set_token_ids():
    rs = ResultSet(
        set_id="0xcond",
        description="Test?",
        kind="binary",
        outcomes=(Outcome("1", "Yes"), Outcome("2", "No")),
    )
    assert rs.token_ids == ["1", "2"]


def test_set_purchase_derived_values():
    rs = ResultSet("s", "d", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))
    fills = (
        Fill("1", "Yes", Decimal("10"), Decimal("0.55"), Decimal("5.5")),
        Fill("2", "No", Decimal("10"), Decimal("0.42"), Decimal("4.2")),
    )
    sp = SetPurchase(rs, Decimal("10"), fills, Decimal("9.7"))
    assert sp.cost_per_set == Decimal("0.97")
    assert sp.guaranteed_payout == Decimal("10")
    assert sp.locked_profit == Decimal("0.3")


def test_set_purchase_can_have_zero_payout_floor():
    rs = ResultSet("s", "d", "momentum", (Outcome("1", "Yes"),))
    fills = (Fill("1", "Yes", Decimal("10"), Decimal("0.55"), Decimal("5.5")),)
    sp = SetPurchase(
        rs,
        Decimal("10"),
        fills,
        Decimal("5.5"),
        payout_floor_per_set=Decimal("0"),
    )

    assert sp.guaranteed_payout == Decimal("0")
    assert sp.locked_profit == Decimal("-5.5")


def test_opportunity_fields():
    rs = ResultSet("s", "d", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))
    opp = Opportunity(rs, {"1": Decimal("0.55"), "2": Decimal("0.42")},
                      Decimal("0.97"), Decimal("0.03"))
    assert opp.edge == Decimal("0.03")
