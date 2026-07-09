from datetime import datetime, timedelta, timezone
from decimal import Decimal

from agent.market_data import BookSnapshot
from agent.models import BookLevel, Fill, OrderBook, Outcome, ResultSet, SetPurchase
from agent.paper_broker import PaperBroker, PaperOrder
from agent.portfolio import Portfolio
from agent.strategies import EntryProposal


NOW = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def book(token, ask="0.55", bid="0.53", size="100"):
    return OrderBook(
        token,
        bids=[BookLevel(Decimal(bid), Decimal(size))],
        asks=[BookLevel(Decimal(ask), Decimal(size))],
    )


def result_set():
    return ResultSet(
        "0xc1",
        "Paper pair",
        "binary",
        (Outcome("101", "Yes"), Outcome("102", "No")),
    )


def order(max_total_cost=Decimal("9.7")):
    return PaperOrder(
        id=None,
        strategy="complete_set",
        side="buy",
        kind="basket",
        result_set=result_set(),
        target_qty=Decimal("10"),
        max_total_cost=max_total_cost,
        min_total_proceeds=None,
        time_in_force="ioc",
        status="submitted",
        created_at=NOW,
        updated_at=NOW,
    )


def snapshot(books=None, fetched_at=NOW, source="polymarket_cli"):
    return BookSnapshot(
        fetched_at=fetched_at,
        source=source,
        books=books or {
            "101": book("101", ask="0.55", bid="0.53"),
            "102": book("102", ask="0.42", bid="0.40"),
        },
    )


def broker(tmp_path, bucket_usd=Decimal("1000")):
    portfolio = Portfolio(str(tmp_path / "ledger.db"), Decimal("1000"))
    return PaperBroker(
        portfolio,
        max_concurrent_positions=10,
        strategy_buckets={"complete_set": bucket_usd},
        max_book_age_seconds=10,
    ), portfolio


def test_ioc_basket_order_fills_from_fresh_polymarket_snapshot(tmp_path):
    b, portfolio = broker(tmp_path)
    submitted = b.submit_order(order())

    report = b.match_open_orders(snapshot(), now=NOW)

    assert submitted.status == "open"
    assert report.filled == 1
    assert report.rejected == 0
    assert portfolio.summary().open_positions == 1
    assert portfolio.cash() == Decimal("990.3")


def test_ioc_order_rejects_missing_fresh_leg_book(tmp_path):
    b, portfolio = broker(tmp_path)
    b.submit_order(order())

    report = b.match_open_orders(
        snapshot(books={"101": book("101", ask="0.55", bid="0.53")}),
        now=NOW,
    )

    assert report.filled == 0
    assert report.rejected == 1
    assert "missing fresh book" in report.messages[0]
    assert portfolio.summary().open_positions == 0


def test_stale_snapshot_does_not_fill_order(tmp_path):
    b, portfolio = broker(tmp_path)
    b.submit_order(order())

    report = b.match_open_orders(
        snapshot(fetched_at=NOW - timedelta(seconds=30)),
        now=NOW,
    )

    assert report.filled == 0
    assert report.rejected == 0
    assert report.skipped == 1
    assert "stale" in report.messages[0]
    assert b.open_orders()[0].status == "open"
    assert portfolio.summary().open_positions == 0


def test_cost_above_limit_rejects_order(tmp_path):
    b, portfolio = broker(tmp_path)
    b.submit_order(order(max_total_cost=Decimal("9.0")))

    report = b.match_open_orders(snapshot(), now=NOW)

    assert report.filled == 0
    assert report.rejected == 1
    assert "cost exceeds max_total_cost" in report.messages[0]
    assert portfolio.summary().open_positions == 0


def test_order_from_entry_proposal_preserves_strategy_and_limits():
    rs = result_set()
    purchase = SetPurchase(
        rs,
        Decimal("10"),
        (
            Fill("101", "Yes", Decimal("10"), Decimal("0.55"), Decimal("5.5")),
            Fill("102", "No", Decimal("10"), Decimal("0.42"), Decimal("4.2")),
        ),
        Decimal("9.7"),
    )
    proposal = EntryProposal("implication", purchase, "edge=0.03")

    converted = PaperOrder.from_entry_proposal(proposal, created_at=NOW)

    assert converted.strategy == "implication"
    assert converted.target_qty == purchase.n_sets
    assert converted.max_total_cost == purchase.total_cost
    assert converted.result_set is purchase.result_set
