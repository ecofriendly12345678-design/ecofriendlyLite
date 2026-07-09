from datetime import datetime, timezone
from decimal import Decimal

from agent.dashboard import load_dashboard_state
from agent.market_data import BookSnapshot
from agent.models import BookLevel, OrderBook, Outcome, ResultSet
from agent.paper_broker import PaperBroker, PaperOrder
from agent.portfolio import Portfolio


NOW = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _book(token_id: str, ask: str, bid: str) -> OrderBook:
    return OrderBook(
        token_id,
        bids=[BookLevel(Decimal(bid), Decimal("100"))],
        asks=[BookLevel(Decimal(ask), Decimal("100"))],
    )


def _seed_trade(db_path: str) -> None:
    portfolio = Portfolio(db_path, Decimal("1000"))
    broker = PaperBroker(
        portfolio,
        max_concurrent_positions=10,
        strategy_buckets={"complete_set": Decimal("500")},
        max_book_age_seconds=10,
    )
    result_set = ResultSet(
        "0xc1",
        "Dashboard pair",
        "binary",
        (Outcome("101", "Yes"), Outcome("102", "No")),
    )
    broker.submit_order(
        PaperOrder(
            id=None,
            strategy="complete_set",
            side="buy",
            kind="basket",
            result_set=result_set,
            target_qty=Decimal("10"),
            max_total_cost=Decimal("9.7"),
            min_total_proceeds=None,
            time_in_force="ioc",
            status="submitted",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    broker.match_open_orders(
        BookSnapshot(
            NOW,
            "polymarket_cli",
            {
                "101": _book("101", "0.55", "0.53"),
                "102": _book("102", "0.42", "0.40"),
            },
        ),
        now=NOW,
    )
    portfolio.mark_to_market({"101": Decimal("0.54"), "102": Decimal("0.41")})


def test_load_dashboard_state_returns_orders_fills_positions_and_pnl(tmp_path):
    db_path = str(tmp_path / "ledger.db")
    _seed_trade(db_path)

    state = load_dashboard_state(db_path)

    assert state["summary"]["cash"] == "990.3"
    assert state["summary"]["open_positions"] == 1
    assert state["orders"][0]["strategy"] == "complete_set"
    assert state["orders"][0]["status"] == "filled"
    assert state["fills"][0]["source"] == "polymarket_cli"
    assert state["positions"][0]["description"] == "Dashboard pair"
    assert state["equity_curve"][-1]["total_equity"] == "999.8"


def test_load_dashboard_state_handles_empty_db(tmp_path):
    state = load_dashboard_state(str(tmp_path / "missing.db"))

    assert state["summary"]["cash"] == "0"
    assert state["orders"] == []
    assert state["fills"] == []
