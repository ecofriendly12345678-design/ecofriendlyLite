"""Plain-text rendering for the loop. No business logic here."""
from __future__ import annotations

from agent.market_data import BookSnapshot
from agent.models import Opportunity
from agent.portfolio import Summary
from agent.strategies import EntryProposal


def _fmt(d) -> str:
    return f"${d:,.2f}"


def render_summary(s: Summary) -> str:
    return (
        f"cash={_fmt(s.cash)} | positions={s.open_positions} | "
        f"value={_fmt(s.positions_value)} | equity={_fmt(s.total_equity)} | "
        f"uPnL={_fmt(s.unrealized_pnl)} | lockedPnL={_fmt(s.guaranteed_pnl)}"
    )


def render_market_data(snapshot: BookSnapshot) -> str:
    return (
        f"market_data source={snapshot.source} "
        f"fetched_at={snapshot.fetched_at.isoformat()} "
        f"tokens={len(snapshot.books)}"
    )


def render_opportunity(opp: Opportunity, acted: bool, reason: str) -> str:
    mark = "TRADED" if acted else "SKIP"
    return (
        f"[{mark}] {opp.result_set.kind} {opp.result_set.description[:60]!r} "
        f"cost/set={opp.cost} edge={opp.edge} ({reason})"
    )


def render_entry_proposal(proposal: EntryProposal, acted: bool, reason: str) -> str:
    mark = "TRADED" if acted else "SKIP"
    purchase = proposal.purchase
    rs = purchase.result_set
    return (
        f"[{mark}] {proposal.strategy} {rs.kind} {rs.description[:60]!r} "
        f"cost/set={purchase.cost_per_set} ({reason})"
    )
