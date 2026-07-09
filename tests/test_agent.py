import json
from decimal import Decimal

from agent.agent import build_result_sets, tick
from agent.config import Config, WatchlistEntry
from agent.portfolio import Portfolio


class FakeCli:
    """In-memory PolymarketCli double: same method names/signatures."""

    def __init__(self, markets=None, events=None, books=None):
        self.markets = markets or {}
        self.events = events or {}
        self.books = books or {}

    def get_market(self, ref):
        return self.markets[ref]

    def get_event(self, ref):
        return self.events[ref]

    def get_books(self, token_ids):
        return {t: self.books[t] for t in token_ids if t in self.books}

    def get_midpoints(self, token_ids):
        raise AssertionError("mids must derive from books, not extra CLI calls")


def market_json(cond="0xc1", yes="101", no="102"):
    return {
        "conditionId": cond, "question": "Q?", "slug": "q",
        "active": True, "closed": False, "enableOrderBook": True,
        "clobTokenIds": json.dumps([yes, no]),
        "outcomes": json.dumps(["Yes", "No"]),
    }


def raw_book(token, ask, bid, size="1000"):
    return {"asset_id": token,
            "asks": [{"price": ask, "size": size}],
            "bids": [{"price": bid, "size": size}]}


def cfg(tmp_path, min_edge="0.01"):
    return Config(
        virtual_capital_usd=Decimal("1000"),
        poll_interval_seconds=0.01,
        min_edge=Decimal(min_edge),
        est_fee=Decimal("0"),
        max_notional_per_trade_usd=Decimal("50"),
        max_concurrent_positions=10,
        sanity_min_mid_sum=Decimal("0.90"),
        db_path=str(tmp_path / "ledger.db"),
        watchlist=(WatchlistEntry("binary", "q"),),
    )


def test_build_result_sets_binary(tmp_path):
    cli = FakeCli(markets={"q": market_json()})
    sets = build_result_sets(cli, (WatchlistEntry("binary", "q"),))
    assert len(sets) == 1
    assert sets[0].token_ids == ["101", "102"]


def test_build_result_sets_skips_failures(tmp_path, capsys):
    class Boom(FakeCli):
        def get_market(self, ref):
            raise RuntimeError("api down")
    sets = build_result_sets(Boom(), (WatchlistEntry("binary", "q"),))
    assert sets == []


def test_tick_opens_position_on_arb(tmp_path):
    c = cfg(tmp_path)
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.42", "0.40")},
    )
    sets = build_result_sets(cli, c.watchlist)
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets, portfolio, c)
    assert s.open_positions == 1
    assert s.guaranteed_pnl > 0
    assert portfolio.has_open_position("0xc1")


def test_tick_no_arb_no_position(tmp_path):
    c = cfg(tmp_path)
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.46", "0.44")},
    )
    sets = build_result_sets(cli, c.watchlist)
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets, portfolio, c)
    assert s.open_positions == 0


def test_tick_does_not_reopen_same_set(tmp_path):
    c = cfg(tmp_path)
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.42", "0.40")},
    )
    sets = build_result_sets(cli, c.watchlist)
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    tick(cli, sets, portfolio, c)
    s2 = tick(cli, sets, portfolio, c)
    assert s2.open_positions == 1  # still exactly one


def test_tick_mtm_reconciles(tmp_path):
    c = cfg(tmp_path)
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.42", "0.40")},
    )
    sets = build_result_sets(cli, c.watchlist)
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets, portfolio, c)
    assert s.total_equity == s.cash + s.positions_value
