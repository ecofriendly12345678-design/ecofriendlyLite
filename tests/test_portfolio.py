from decimal import Decimal

from agent.models import Fill, Opportunity, Outcome, ResultSet, SetPurchase
from agent.portfolio import Portfolio


def make_purchase(set_id="0xc1", cost="9.7"):
    rs = ResultSet(set_id, "Test?", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))
    fills = (
        Fill("1", "Yes", Decimal("10"), Decimal("0.55"), Decimal("5.5")),
        Fill("2", "No", Decimal("10"), Decimal("0.42"), Decimal("4.2")),
    )
    return SetPurchase(rs, Decimal("10"), fills, Decimal(cost))


def make_opp(set_id="0xc1"):
    rs = ResultSet(set_id, "Test?", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))
    return Opportunity(rs, {"1": Decimal("0.55"), "2": Decimal("0.42")},
                       Decimal("0.97"), Decimal("0.03"))


def db(tmp_path):
    return str(tmp_path / "ledger.db")


def test_fresh_portfolio_cash(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    assert p.cash() == Decimal("1000")


def test_open_position_reduces_cash(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.open_position(make_purchase())
    assert p.cash() == Decimal("990.3")


def test_duplicate_set_blocked(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.open_position(make_purchase())
    ok, reason = p.can_open(Decimal("9.7"), "0xc1", 10)
    assert not ok
    assert "open position" in reason


def test_insufficient_cash_blocked(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("5"))
    ok, reason = p.can_open(Decimal("9.7"), "0xc1", 10)
    assert not ok
    assert "cash" in reason.lower()


def test_max_concurrent_blocked(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.open_position(make_purchase("0xc1"))
    ok, reason = p.can_open(Decimal("9.7"), "0xc2", 1)
    assert not ok
    assert "concurrent" in reason.lower()


def test_can_open_happy(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    ok, reason = p.can_open(Decimal("9.7"), "0xc1", 10)
    assert ok


def test_mark_to_market_reconciles(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.open_position(make_purchase())  # cost 9.7 for 10 sets
    s = p.mark_to_market({"1": Decimal("0.60"), "2": Decimal("0.42")})
    # value = 10*0.60 + 10*0.42 = 10.2; cash = 990.3; equity = 1000.5
    assert s.positions_value == Decimal("10.2")
    assert s.cash == Decimal("990.3")
    assert s.total_equity == Decimal("1000.5")
    assert s.unrealized_pnl == Decimal("0.5")
    # guaranteed: 10 sets pay $10 at resolution, cost 9.7 -> +0.3
    assert s.guaranteed_pnl == Decimal("0.3")


def test_mark_to_market_missing_mid_uses_last(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.open_position(make_purchase())
    p.mark_to_market({"1": Decimal("0.60"), "2": Decimal("0.42")})
    s = p.mark_to_market({"1": Decimal("0.65")})  # token 2 missing -> last mid 0.42
    assert s.positions_value == Decimal("10.7")


def test_restart_preserves_state(tmp_path):
    path = db(tmp_path)
    p1 = Portfolio(path, Decimal("1000"))
    p1.open_position(make_purchase())
    p2 = Portfolio(path, Decimal("999999"))  # new starting capital ignored on reopen
    assert p2.cash() == Decimal("990.3")
    assert p2.has_open_position("0xc1")


def test_record_opportunity(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.record_opportunity(make_opp(), acted=False, reason="edge below threshold")
    import sqlite3
    rows = sqlite3.connect(db(tmp_path)).execute(
        "SELECT set_id, acted, reason FROM opportunities").fetchall()
    assert rows == [("0xc1", 0, "edge below threshold")]
