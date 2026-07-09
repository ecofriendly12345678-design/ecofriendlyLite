"""v1 complete-set arbitrage exposed as a v2 strategy plugin."""
from __future__ import annotations

from decimal import Decimal

from agent.fills import plan_set_purchase
from agent.models import OrderBook, ResultSet
from agent.scanner import find_opportunities
from agent.strategies import EntryProposal, ExitProposal, OpenPosition, TickContext, decimal_config


class CompleteSetStrategy:
    name = "complete_set"

    def __init__(self, result_sets: list[ResultSet]):
        self._sets = list(result_sets)

    def required_tokens(self) -> list[str]:
        tokens: list[str] = []
        seen: set[str] = set()
        for result_set in self._sets:
            for token_id in result_set.token_ids:
                if token_id not in seen:
                    seen.add(token_id)
                    tokens.append(token_id)
        return tokens

    def propose_entries(
        self, books: dict[str, OrderBook], ctx: TickContext,
    ) -> list[EntryProposal]:
        min_edge = decimal_config(ctx, "min_edge")
        est_fee = decimal_config(ctx, "est_fee")
        sanity_min_mid_sum = decimal_config(ctx, "sanity_min_mid_sum")
        max_notional = decimal_config(ctx, "max_notional_per_trade_usd")

        proposals: list[EntryProposal] = []
        for opp in find_opportunities(
            self._sets, books, min_edge, est_fee, sanity_min_mid_sum,
        ):
            purchase = plan_set_purchase(
                opp.result_set,
                books,
                max_cost_per_set=Decimal("1") - min_edge - est_fee,
                max_notional=max_notional,
            )
            if purchase is None:
                continue
            proposals.append(
                EntryProposal(
                    strategy=self.name,
                    purchase=purchase,
                    reason=f"complete set edge={opp.edge} cost/set={opp.cost}",
                )
            )
        return proposals

    def propose_exits(
        self,
        books: dict[str, OrderBook],
        open_positions: list[OpenPosition],
        ctx: TickContext,
    ) -> list[ExitProposal]:
        return []
