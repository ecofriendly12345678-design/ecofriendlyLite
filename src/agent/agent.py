"""Real-time polling loop. One tick = fetch books -> scan -> risk-check ->
simulate fills -> ledger -> mark-to-market -> report."""
from __future__ import annotations

import argparse
import time
from decimal import Decimal

from agent import report
from agent.cli import CliError, PolymarketCli
from agent.config import Config, WatchlistEntry, load_config
from agent.fills import plan_set_purchase
from agent.models import OrderBook, ResultSet
from agent.portfolio import Portfolio, Summary
from agent.scanner import find_opportunities, result_set_from_event, result_set_from_market


def build_result_sets(cli, watchlist: tuple[WatchlistEntry, ...]) -> list[ResultSet]:
    sets: list[ResultSet] = []
    for entry in watchlist:
        try:
            if entry.type == "binary":
                rs = result_set_from_market(cli.get_market(entry.ref))
            else:
                rs = result_set_from_event(cli.get_event(entry.ref))
        except Exception as e:  # noqa: BLE001 - one bad entry must not kill the loop
            print(f"warn: watchlist entry {entry.ref!r} failed: {e}")
            continue
        if rs is None:
            print(f"warn: watchlist entry {entry.ref!r} is not tradeable, skipping")
            continue
        sets.append(rs)
    return sets


def tick(cli, sets: list[ResultSet], portfolio: Portfolio, cfg: Config) -> Summary:
    all_tokens = sorted({t for rs in sets for t in rs.token_ids})
    raw_books = cli.get_books(all_tokens)
    books = {tid: OrderBook.from_json(b) for tid, b in raw_books.items()}

    opps = find_opportunities(
        sets, books, cfg.min_edge, cfg.est_fee, cfg.sanity_min_mid_sum
    )
    for opp in opps:
        ok, reason = portfolio.can_open(
            cfg.max_notional_per_trade_usd, opp.result_set.set_id,
            cfg.max_concurrent_positions,
        )
        if not ok:
            portfolio.record_opportunity(opp, acted=False, reason=reason)
            print(report.render_opportunity(opp, False, reason))
            continue
        purchase = plan_set_purchase(
            opp.result_set, books,
            max_cost_per_set=Decimal("1") - cfg.min_edge - cfg.est_fee,
            max_notional=min(cfg.max_notional_per_trade_usd, portfolio.cash()),
        )
        if purchase is None:
            portfolio.record_opportunity(opp, acted=False, reason="insufficient depth")
            print(report.render_opportunity(opp, False, "insufficient depth"))
            continue
        portfolio.open_position(purchase)
        reason = (f"bought {purchase.n_sets} sets @ {purchase.cost_per_set} "
                  f"locked={purchase.locked_profit}")
        portfolio.record_opportunity(opp, acted=True, reason=reason)
        print(report.render_opportunity(opp, True, reason))

    mids = {tid: b.midpoint for tid, b in books.items() if b.midpoint is not None}
    return portfolio.mark_to_market(mids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Polymarket paper-trading arb agent")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="run a single tick")
    parser.add_argument("--refresh-every", type=int, default=60,
                        help="rebuild result sets every N ticks")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    cli = PolymarketCli()
    portfolio = Portfolio(cfg.db_path, cfg.virtual_capital_usd)

    print(f"watchlist: {len(cfg.watchlist)} entries; paper capital "
          f"${cfg.virtual_capital_usd}; poll every {cfg.poll_interval_seconds}s "
          f"(read-only, fills are simulated)")
    sets = build_result_sets(cli, cfg.watchlist)
    if not sets:
        print("error: no tradeable sets in watchlist")
        return 1
    print(f"tracking {len(sets)} result sets, "
          f"{sum(len(rs.outcomes) for rs in sets)} outcome tokens")

    n = 0
    while True:
        try:
            summary = tick(cli, sets, portfolio, cfg)
            print(report.render_summary(summary))
        except CliError as e:
            print(f"warn: tick failed: {e}")
        except KeyboardInterrupt:
            print("\nstopping.")
            return 0
        except Exception as e:  # noqa: BLE001 - loop must survive surprises
            print(f"error: unexpected failure in tick: {e!r}")
        if args.once:
            return 0
        n += 1
        if n % args.refresh_every == 0:
            sets = build_result_sets(cli, cfg.watchlist) or sets
        try:
            time.sleep(cfg.poll_interval_seconds)
        except KeyboardInterrupt:
            print("\nstopping.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
