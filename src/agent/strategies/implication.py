"""Cross-market implication arbitrage.

For a manually verified relation A => B, buy NO(A) + YES(B). The pair pays at
least $1 unless the manually declared implication is wrong.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import yaml

from agent.fills import plan_set_purchase
from agent.models import Opportunity, OrderBook, Outcome, ResultSet
from agent.scanner import result_set_from_market
from agent.strategies import EntryProposal, ExitProposal, OpenPosition, TickContext, decimal_config


@dataclass(frozen=True)
class ImplicationRelation:
    if_ref: str
    then_ref: str
    note: str


def load_implication_relations(path: str) -> list[ImplicationRelation]:
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("implications"), list):
        raise ValueError("implications file must contain an 'implications' list")

    relations: list[ImplicationRelation] = []
    for i, item in enumerate(data["implications"]):
        if not isinstance(item, dict):
            raise ValueError(f"implications[{i}] must be a mapping")
        if_ref = str(item.get("if", "")).strip()
        then_ref = str(item.get("then", "")).strip()
        note = str(item.get("note", "")).strip()
        if not if_ref:
            raise ValueError(f"implications[{i}].if is required")
        if not then_ref:
            raise ValueError(f"implications[{i}].then is required")
        if not note:
            raise ValueError(f"implications[{i}].note is required")
        relations.append(ImplicationRelation(if_ref=if_ref, then_ref=then_ref, note=note))
    return relations


def implication_set_from_markets(
    if_market: dict, then_market: dict, note: str,
) -> ResultSet | None:
    if_set = result_set_from_market(if_market)
    then_set = result_set_from_market(then_market)
    if if_set is None or then_set is None:
        return None
    if len(if_set.outcomes) != 2 or len(then_set.outcomes) != 2:
        return None

    no_if = if_set.outcomes[1]
    yes_then = then_set.outcomes[0]
    return ResultSet(
        set_id=f"implication:{if_set.set_id}=>{then_set.set_id}",
        description=f"{if_set.description} => {then_set.description} ({note})",
        kind="implication",
        outcomes=(
            Outcome(no_if.token_id, f"NO({if_set.description})"),
            Outcome(yes_then.token_id, f"YES({then_set.description})"),
        ),
    )


def build_implication_sets(cli, relations: list[ImplicationRelation]) -> list[ResultSet]:
    result_sets: list[ResultSet] = []
    for relation in relations:
        try:
            result_set = implication_set_from_markets(
                cli.get_market(relation.if_ref),
                cli.get_market(relation.then_ref),
                relation.note,
            )
        except Exception as e:  # noqa: BLE001 - one bad relation should not kill the loop
            print(
                "warn: implication relation "
                f"{relation.if_ref!r}=>{relation.then_ref!r} failed: {e}"
            )
            continue
        if result_set is None:
            print(
                "warn: implication relation "
                f"{relation.if_ref!r}=>{relation.then_ref!r} is not tradeable"
            )
            continue
        result_sets.append(result_set)
    return result_sets


class ImplicationStrategy:
    name = "implication"

    def __init__(self, result_sets: list[ResultSet]):
        self._sets = list(result_sets)

    @classmethod
    def from_file(cls, cli, path: str) -> ImplicationStrategy:
        return cls(build_implication_sets(cli, load_implication_relations(path)))

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
        max_notional = decimal_config(ctx, "max_notional_per_trade_usd")

        proposals: list[EntryProposal] = []
        for result_set in self._sets:
            opp = self._find_opportunity(result_set, books, min_edge, est_fee)
            if opp is None:
                continue
            purchase = plan_set_purchase(
                result_set,
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
                    reason=f"implication edge={opp.edge} cost/set={opp.cost}",
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

    def _find_opportunity(
        self,
        result_set: ResultSet,
        books: dict[str, OrderBook],
        min_edge: Decimal,
        est_fee: Decimal,
    ) -> Opportunity | None:
        asks = {}
        for token_id in result_set.token_ids:
            book = books.get(token_id)
            if book is None or book.best_ask is None:
                return None
            asks[token_id] = book.best_ask.price
        cost = sum(asks.values(), Decimal("0"))
        edge = Decimal("1") - cost
        if edge > min_edge + est_fee:
            return Opportunity(result_set, asks, cost, edge)
        return None
