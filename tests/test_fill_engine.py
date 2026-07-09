from datetime import datetime, timezone
from decimal import Decimal

from agent.fill_engine import simulate_basket_buy, simulate_buy_leg, simulate_sell_leg
from agent.market_data import BookSnapshot
from agent.models import BookLevel, OrderBook, Outcome, ResultSet


def book(token_id):
    return OrderBook(
        token_id,
        bids=[
            BookLevel(Decimal("0.50"), Decimal("5")),
            BookLevel(Decimal("0.40"), Decimal("10")),
        ],
        asks=[
            BookLevel(Decimal("0.55"), Decimal("5")),
            BookLevel(Decimal("0.60"), Decimal("10")),
        ],
    )


def test_book_snapshot_records_live_source():
    snapshot = BookSnapshot(
        datetime(2026, 7, 9, tzinfo=timezone.utc),
        "polymarket_cli",
        {"1": book("1")},
    )
    assert snapshot.source == "polymarket_cli"
    assert snapshot.books["1"].best_ask.price == Decimal("0.55")


def test_simulate_buy_leg_walks_asks():
    fill = simulate_buy_leg(book("1"), "Yes", Decimal("6"))
    assert fill.avg_price == Decimal("3.35") / Decimal("6")
    assert fill.amount == Decimal("3.35")


def test_simulate_sell_leg_walks_bids():
    fill = simulate_sell_leg(book("1"), "Yes", Decimal("6"))
    assert fill.avg_price == Decimal("2.90") / Decimal("6")
    assert fill.amount == Decimal("2.90")


def test_simulate_basket_buy_requires_all_legs():
    rs = ResultSet("s", "Pair", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))
    assert simulate_basket_buy(rs, {"1": book("1")}, Decimal("1")) is None
