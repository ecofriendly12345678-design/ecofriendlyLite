"""Real-time polling loop. One tick = fetch books -> scan -> simulate fills ->
risk-check -> ledger -> mark-to-market -> report."""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from decimal import Decimal

from agent import report
from agent.cli import CliError, PolymarketCli
from agent.config import Config, WatchlistEntry, load_config
from agent.market_data import BookSnapshot
from agent.models import OrderBook, ResultSet
from agent.paper_broker import PaperBroker, PaperOrder
from agent.portfolio import Portfolio, Summary
from agent.scanner import result_set_from_event, result_set_from_market
from agent.strategies import EntryProposal, StrategyProtocol, TickContext
from agent.strategies.complete_set import CompleteSetStrategy
from agent.strategies.implication import ImplicationStrategy


def build_result_sets(
    cli, watchlist: tuple[WatchlistEntry, ...],
) -> tuple[dict[str, ResultSet], set[str]]:
    """Resolve watchlist entries. Returns (sets keyed by entry ref, refs that
    errored). A ref that resolves but is not tradeable (closed market) appears
    in neither — callers should drop it. A ref that errored (transient CLI
    failure) is reported so callers can keep a previously known-good set."""
    sets: dict[str, ResultSet] = {}
    errored: set[str] = set()
    for entry in watchlist:
        try:
            if entry.type == "binary":
                rs = result_set_from_market(cli.get_market(entry.ref))
            else:
                rs = result_set_from_event(cli.get_event(entry.ref))
        except Exception as e:  # noqa: BLE001 - one bad entry must not kill the loop
            print(f"warn: watchlist entry {entry.ref!r} failed: {e}")
            errored.add(entry.ref)
            continue
        if rs is None:
            print(f"warn: watchlist entry {entry.ref!r} is not tradeable, skipping")
            continue
        sets[entry.ref] = rs
    return sets, errored


def merge_refresh(
    old: dict[str, ResultSet],
    new: dict[str, ResultSet],
    errored: set[str],
) -> dict[str, ResultSet]:
    """Refresh policy: take the new resolution; keep the previous set for
    entries that merely errored (transient failure != market gone); drop
    entries that resolved as not-tradeable (absent from both new and errored)."""
    merged = dict(new)
    for ref in errored:
        if ref in old:
            merged[ref] = old[ref]
    return merged


def build_strategies(cli, sets: list[ResultSet], cfg: Config) -> list[StrategyProtocol]:
    strategies: list[StrategyProtocol] = []
    complete_set_cfg = cfg.strategies.get("complete_set") if cfg.strategies else None
    if complete_set_cfg is None or complete_set_cfg.enabled:
        strategies.append(CompleteSetStrategy(sets))

    implication_cfg = cfg.strategies.get("implication") if cfg.strategies else None
    if implication_cfg is not None and implication_cfg.enabled:
        if not implication_cfg.relations_file:
            print("warn: implication enabled but no relations_file configured")
        else:
            try:
                strategies.append(
                    ImplicationStrategy.from_file(cli, implication_cfg.relations_file)
                )
            except Exception as e:  # noqa: BLE001 - bad optional strategy must not kill v1
                print(f"warn: implication strategy failed to load: {e}")
    return strategies


def _strategy_context(
    cfg: Config,
    portfolio: Portfolio,
    strategy_name: str,
    now: datetime,
) -> TickContext:
    strategy_cfg = cfg.strategies.get(strategy_name) if cfg.strategies else None
    section = dict(strategy_cfg.params or {}) if strategy_cfg is not None else {}
    section.update({
        "min_edge": cfg.min_edge,
        "est_fee": cfg.est_fee,
        "sanity_min_mid_sum": cfg.sanity_min_mid_sum,
        "max_notional_per_trade_usd": min(
            cfg.max_notional_per_trade_usd,
            portfolio.cash(),
        ),
    })
    return TickContext(now=now, config_section=section)


def _strategy_buckets(cfg: Config) -> dict[str, Decimal]:
    if not cfg.strategies:
        return {"complete_set": cfg.virtual_capital_usd}
    return {name: strategy.bucket_usd for name, strategy in cfg.strategies.items()}


def tick(cli, sets: list[ResultSet], portfolio: Portfolio, cfg: Config) -> Summary:
    strategies = build_strategies(cli, sets, cfg)
    all_tokens = sorted({t for strategy in strategies for t in strategy.required_tokens()})
    raw_books = cli.get_books(all_tokens)
    books = {tid: OrderBook.from_json(b) for tid, b in raw_books.items()}
    snapshot = BookSnapshot(
        fetched_at=datetime.now(timezone.utc),
        source="polymarket_cli",
        books=books,
    )
    print(report.render_market_data(snapshot))
    broker = PaperBroker(
        portfolio,
        max_concurrent_positions=cfg.max_concurrent_positions,
        strategy_buckets=_strategy_buckets(cfg),
        max_book_age_seconds=max(cfg.poll_interval_seconds * 2, 1),
    )
    # Tokens already bought this tick: a second set sharing a token would be
    # filled against depth the first purchase already (virtually) consumed.
    used_tokens: set[str] = set()
    for strategy in strategies:
        ctx = _strategy_context(cfg, portfolio, strategy.name, snapshot.fetched_at)
        for proposal in strategy.propose_entries(books, ctx):
            purchase = proposal.purchase
            rs = purchase.result_set
            if used_tokens & set(rs.token_ids):
                reason = "token overlap with an earlier trade this tick"
                print(report.render_entry_proposal(proposal, False, reason))
                continue
            order = PaperOrder.from_entry_proposal(proposal, created_at=snapshot.fetched_at)
            submit = broker.submit_order(order)
            match = broker.match_open_orders(snapshot, now=snapshot.fetched_at)
            acted = match.filled > 0
            if acted:
                used_tokens.update(rs.token_ids)
                reason = (f"paper order {submit.order_id} filled {purchase.n_sets} sets "
                          f"@ {purchase.cost_per_set} locked={purchase.locked_profit}")
            else:
                reason = match.messages[0] if match.messages else "paper order not filled"
            print(report.render_entry_proposal(proposal, acted, reason))

    mids = {tid: b.midpoint for tid, b in books.items() if b.midpoint is not None}
    return portfolio.mark_to_market(mids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Polymarket paper-trading arb agent")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="run a single tick")
    parser.add_argument("--refresh-every", type=int, default=60,
                        help="rebuild result sets every N ticks (N >= 1)")
    args = parser.parse_args(argv)
    if args.refresh_every < 1:
        parser.error("--refresh-every must be >= 1")

    cfg = load_config(args.config)
    cli = PolymarketCli()
    portfolio = Portfolio(cfg.db_path, cfg.virtual_capital_usd)

    print(f"watchlist: {len(cfg.watchlist)} entries; paper capital "
          f"${cfg.virtual_capital_usd}; poll every {cfg.poll_interval_seconds}s "
          f"(read-only, fills are simulated)")

    # Everything below may block in subprocess calls; one handler gives Ctrl-C
    # a clean exit no matter where it lands (tick, refresh, or sleep).
    try:
        sets_by_ref, _ = build_result_sets(cli, cfg.watchlist)
        if not sets_by_ref:
            print("error: no tradeable sets in watchlist")
            return 1
        print(f"tracking {len(sets_by_ref)} result sets, "
              f"{sum(len(rs.outcomes) for rs in sets_by_ref.values())} outcome tokens")

        n = 0
        while True:
            try:
                summary = tick(cli, list(sets_by_ref.values()), portfolio, cfg)
                print(report.render_summary(summary))
            except CliError as e:
                print(f"warn: tick failed: {e}")
            except Exception as e:  # noqa: BLE001 - loop must survive surprises
                print(f"error: unexpected failure in tick: {e!r}")
            if args.once:
                return 0
            n += 1
            if n % args.refresh_every == 0:
                new_sets, errored = build_result_sets(cli, cfg.watchlist)
                sets_by_ref = merge_refresh(sets_by_ref, new_sets, errored)
                if not sets_by_ref:
                    print("error: watchlist has no tradeable sets left")
                    return 1
            time.sleep(cfg.poll_interval_seconds)
    except KeyboardInterrupt:
        print("\nstopping.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
