"""Plain-text rendering for the loop. No business logic here."""
from __future__ import annotations

from agent.models import Opportunity
from agent.portfolio import Summary


def _fmt(d) -> str:
    return f"${d:,.2f}"


def render_summary(s: Summary) -> str:
    return (
        f"cash={_fmt(s.cash)} | positions={s.open_positions} | "
        f"value={_fmt(s.positions_value)} | equity={_fmt(s.total_equity)} | "
        f"uPnL={_fmt(s.unrealized_pnl)} | lockedPnL={_fmt(s.guaranteed_pnl)}"
    )


def render_opportunity(opp: Opportunity, acted: bool, reason: str) -> str:
    mark = "TRADED" if acted else "SKIP"
    return (
        f"[{mark}] {opp.result_set.kind} {opp.result_set.description[:60]!r} "
        f"cost/set={opp.cost} edge={opp.edge} ({reason})"
    )
