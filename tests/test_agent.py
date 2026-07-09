import json
from decimal import Decimal

import pytest

from agent.agent import build_result_sets, main, merge_refresh, tick
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


def market_json(cond="0xc1", yes="101", no="102", slug="q"):
    return {
        "conditionId": cond, "question": "Q?", "slug": slug,
        "active": True, "closed": False, "enableOrderBook": True,
        "clobTokenIds": json.dumps([yes, no]),
        "outcomes": json.dumps(["Yes", "No"]),
    }


def raw_book(token, ask, bid, size="1000"):
    return {"asset_id": token,
            "asks": [{"price": ask, "size": size}],
            "bids": [{"price": bid, "size": size}]}


def cfg(tmp_path, min_edge="0.01", capital="1000", watchlist=None):
    return Config(
        virtual_capital_usd=Decimal(capital),
        poll_interval_seconds=0.01,
        min_edge=Decimal(min_edge),
        est_fee=Decimal("0"),
        max_notional_per_trade_usd=Decimal("50"),
        max_concurrent_positions=10,
        sanity_min_mid_sum=Decimal("0.90"),
        db_path=str(tmp_path / "ledger.db"),
        watchlist=watchlist or (WatchlistEntry("binary", "q"),),
    )


def sets_list(cli, watchlist):
    sets_by_ref, _ = build_result_sets(cli, watchlist)
    return list(sets_by_ref.values())


def test_build_result_sets_binary(tmp_path):
    cli = FakeCli(markets={"q": market_json()})
    sets_by_ref, errored = build_result_sets(cli, (WatchlistEntry("binary", "q"),))
    assert errored == set()
    assert list(sets_by_ref) == ["q"]
    assert sets_by_ref["q"].token_ids == ["101", "102"]


def test_build_result_sets_reports_failures(tmp_path, capsys):
    class Boom(FakeCli):
        def get_market(self, ref):
            raise RuntimeError("api down")
    sets_by_ref, errored = build_result_sets(Boom(), (WatchlistEntry("binary", "q"),))
    assert sets_by_ref == {}
    assert errored == {"q"}


def test_merge_refresh_keeps_stale_on_error_drops_untradeable():
    cli = FakeCli(markets={"a": market_json(cond="0xa", yes="1", no="2", slug="a"),
                           "b": market_json(cond="0xb", yes="3", no="4", slug="b")})
    old, _ = build_result_sets(
        cli, (WatchlistEntry("binary", "a"), WatchlistEntry("binary", "b")))
    assert set(old) == {"a", "b"}
    # Refresh: 'a' errors transiently (keep stale), 'b' resolves untradeable (drop).
    merged = merge_refresh(old, new={}, errored={"a"})
    assert set(merged) == {"a"}
    assert merged["a"] is old["a"]


def test_tick_opens_position_on_arb(tmp_path):
    c = cfg(tmp_path)
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.42", "0.40")},
    )
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets_list(cli, c.watchlist), portfolio, c)
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
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets_list(cli, c.watchlist), portfolio, c)
    assert s.open_positions == 0


def test_tick_does_not_reopen_same_set(tmp_path):
    c = cfg(tmp_path)
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.42", "0.40")},
    )
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    sets = sets_list(cli, c.watchlist)
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
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets_list(cli, c.watchlist), portfolio, c)
    assert s.total_equity == s.cash + s.positions_value


def test_tick_trades_when_cash_below_per_trade_cap(tmp_path):
    # Review finding regression: with cash ($40) below the per-trade cap
    # ($50), the agent must still size a trade to available cash rather than
    # rejecting with 'insufficient cash'.
    c = cfg(tmp_path, capital="40")
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.42", "0.40")},
    )
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets_list(cli, c.watchlist), portfolio, c)
    assert s.open_positions == 1
    assert portfolio.cash() >= 0
    assert portfolio.cash() < Decimal("40")  # actually spent something


def test_tick_blocks_token_overlap_within_tick(tmp_path):
    # Review finding regression: a binary market also present inside a watched
    # neg-risk event must not be double-filled from the same book in one tick.
    event = {
        "id": "500", "title": "Who wins?", "negRisk": True,
        "markets": [
            {**market_json(cond="0xc1", yes="101", no="102"), "groupItemTitle": "A"},
            {**market_json(cond="0xc9", yes="109", no="110"), "groupItemTitle": "B"},
        ],
    }
    c = cfg(tmp_path, watchlist=(
        WatchlistEntry("binary", "q"), WatchlistEntry("event", "500"),
    ))
    cli = FakeCli(
        markets={"q": market_json()},          # binary set: tokens 101/102
        events={"500": event},                 # event set: YES tokens 101/109
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.42", "0.40"),
               "109": raw_book("109", "0.40", "0.38")},
    )
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets_list(cli, c.watchlist), portfolio, c)
    # Both sets are arbs (0.97 and 0.95) sharing token 101 -> only one opens.
    assert s.open_positions == 1


def test_main_rejects_refresh_every_zero(tmp_path):
    # Review finding regression: --refresh-every 0 must be a usage error, not
    # a ZeroDivisionError after the first tick.
    with pytest.raises(SystemExit) as exc:
        main(["--refresh-every", "0", "--config", "/nonexistent.yaml"])
    assert exc.value.code == 2  # argparse usage error
