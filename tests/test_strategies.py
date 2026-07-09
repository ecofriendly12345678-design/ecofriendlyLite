from datetime import datetime, timezone
from decimal import Decimal

from agent.models import BookLevel, OrderBook, Outcome, ResultSet
from agent.strategies import TickContext
from agent.strategies.complete_set import CompleteSetStrategy
from agent.strategies.implication import (
    ImplicationRelation,
    ImplicationStrategy,
    implication_set_from_markets,
    load_implication_relations,
)


def _book(token_id: str, ask: str, bid: str, size: str = "100") -> OrderBook:
    return OrderBook(
        token_id=token_id,
        asks=[BookLevel(Decimal(ask), Decimal(size))],
        bids=[BookLevel(Decimal(bid), Decimal(size))],
    )


def _ctx(**overrides) -> TickContext:
    config = {
        "min_edge": Decimal("0.01"),
        "est_fee": Decimal("0"),
        "sanity_min_mid_sum": Decimal("0.90"),
        "max_notional_per_trade_usd": Decimal("50"),
    }
    config.update(overrides)
    return TickContext(
        now=datetime(2026, 7, 8, tzinfo=timezone.utc),
        config_section=config,
    )


def _market(cond: str, yes: str, no: str, question: str = "Q?") -> dict:
    return {
        "conditionId": cond,
        "question": question,
        "active": True,
        "closed": False,
        "enableOrderBook": True,
        "clobTokenIds": f'["{yes}", "{no}"]',
        "outcomes": '["Yes", "No"]',
    }


def test_complete_set_strategy_proposes_depth_aware_entry():
    result_set = ResultSet(
        "0xc1", "Binary?", "binary",
        (Outcome("101", "Yes"), Outcome("102", "No")),
    )
    strategy = CompleteSetStrategy([result_set])

    proposals = strategy.propose_entries(
        {
            "101": _book("101", "0.55", "0.53"),
            "102": _book("102", "0.42", "0.40"),
        },
        _ctx(),
    )

    assert strategy.name == "complete_set"
    assert strategy.required_tokens() == ["101", "102"]
    assert strategy.propose_exits({}, [], _ctx()) == []
    assert len(proposals) == 1
    assert proposals[0].strategy == "complete_set"
    assert proposals[0].purchase.result_set is result_set
    assert proposals[0].purchase.locked_profit > 0
    assert "edge=0.03" in proposals[0].reason


def test_complete_set_strategy_skips_when_depth_cannot_satisfy_edge():
    result_set = ResultSet(
        "0xc1", "Binary?", "binary",
        (Outcome("101", "Yes"), Outcome("102", "No")),
    )
    strategy = CompleteSetStrategy([result_set])

    proposals = strategy.propose_entries(
        {
            "101": OrderBook(
                "101",
                asks=[
                    BookLevel(Decimal("0.55"), Decimal("0.005")),
                    BookLevel(Decimal("0.90"), Decimal("100")),
                ],
                bids=[BookLevel(Decimal("0.53"), Decimal("100"))],
            ),
            "102": _book("102", "0.42", "0.40"),
        },
        _ctx(max_notional_per_trade_usd=Decimal("10")),
    )

    assert proposals == []


def test_load_implication_relations_requires_note(tmp_path):
    path = tmp_path / "implications.yaml"
    path.write_text(
        """
implications:
  - if: harder-market
    then: easier-market
    note: "Same source and resolution window checked 2026-07-08"
""".strip()
    )

    assert load_implication_relations(str(path)) == [
        ImplicationRelation(
            if_ref="harder-market",
            then_ref="easier-market",
            note="Same source and resolution window checked 2026-07-08",
        )
    ]


def test_implication_set_uses_no_of_if_and_yes_of_then():
    result_set = implication_set_from_markets(
        _market("0xa", "11", "12", "A happens"),
        _market("0xb", "21", "22", "B happens"),
        note="A implies B; terms checked",
    )

    assert result_set is not None
    assert result_set.kind == "implication"
    assert result_set.set_id == "implication:0xa=>0xb"
    assert result_set.token_ids == ["12", "21"]
    assert result_set.outcomes[0].label == "NO(A happens)"
    assert result_set.outcomes[1].label == "YES(B happens)"


def test_implication_strategy_proposes_without_mid_sum_guard():
    result_set = implication_set_from_markets(
        _market("0xa", "11", "12", "A happens"),
        _market("0xb", "21", "22", "B happens"),
        note="A implies B; terms checked",
    )
    strategy = ImplicationStrategy([result_set])

    proposals = strategy.propose_entries(
        {
            "12": _book("12", "0.44", "0.42"),
            "21": _book("21", "0.52", "0.50"),
        },
        _ctx(sanity_min_mid_sum=Decimal("1.50")),
    )

    assert strategy.name == "implication"
    assert strategy.required_tokens() == ["12", "21"]
    assert len(proposals) == 1
    assert proposals[0].strategy == "implication"
    assert proposals[0].purchase.result_set.kind == "implication"
    assert proposals[0].purchase.locked_profit > 0


def test_implication_strategy_ignores_fair_pair():
    result_set = implication_set_from_markets(
        _market("0xa", "11", "12", "A happens"),
        _market("0xb", "21", "22", "B happens"),
        note="A implies B; terms checked",
    )
    strategy = ImplicationStrategy([result_set])

    proposals = strategy.propose_entries(
        {
            "12": _book("12", "0.50", "0.48"),
            "21": _book("21", "0.52", "0.50"),
        },
        _ctx(),
    )

    assert proposals == []
