from decimal import Decimal

from agent.fills import plan_set_purchase, walk_book
from agent.models import BookLevel, OrderBook, Outcome, ResultSet


def levels(*pairs):
    return [BookLevel(Decimal(p), Decimal(s)) for p, s in pairs]


def book(token, ask_pairs, bid_pairs=(("0.01", "1"),)):
    return OrderBook(
        token_id=token,
        asks=levels(*ask_pairs),
        bids=levels(*bid_pairs),
    )


RS = ResultSet("s", "d", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))


def test_walk_book_single_level():
    cost = walk_book(levels(("0.55", "100")), Decimal("10"))
    assert cost == Decimal("5.5")


def test_walk_book_multiple_levels():
    # 10 @ 0.50 + 5 @ 0.60 = 5.00 + 3.00 = 8.00
    cost = walk_book(levels(("0.50", "10"), ("0.60", "20")), Decimal("15"))
    assert cost == Decimal("8.00")


def test_walk_book_insufficient_depth():
    assert walk_book(levels(("0.50", "10")), Decimal("11")) is None


def test_walk_book_zero_qty():
    assert walk_book(levels(("0.50", "10")), Decimal("0")) is None


def test_plan_set_purchase_happy_path():
    books = {
        "1": book("1", (("0.55", "100"),)),
        "2": book("2", (("0.42", "100"),)),
    }
    sp = plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50"))
    assert sp is not None
    # Depth allows 100 sets (cost 97 > notional 50), so sizing falls to the
    # notional-capped candidate: floor(50 / 0.97, 0.01) = 51.54 sets.
    assert sp.n_sets == Decimal("51.54")
    assert sp.total_cost <= Decimal("50")
    assert sp.cost_per_set == Decimal("0.97")
    assert sp.locked_profit > 0


def test_plan_set_purchase_walks_depth_until_edge_gone():
    # Leg1: 10 @ 0.55 then 0.70; leg2: plentiful @ 0.42.
    # 10 sets: per-set 0.97 <= 0.99 OK. 20 sets: leg1 = 10*0.55+10*0.70=12.5,
    # leg2 = 20*0.42=8.4 -> per-set (12.5+8.4)/20 = 1.045 > 0.99 -> only 10 sets.
    books = {
        "1": book("1", (("0.55", "10"), ("0.70", "1000"))),
        "2": book("2", (("0.42", "1000"),)),
    }
    sp = plan_set_purchase(RS, books, Decimal("0.99"), Decimal("10000"))
    assert sp is not None
    assert sp.n_sets == Decimal("10")
    assert sp.cost_per_set == Decimal("0.97")


def test_plan_set_purchase_thin_book_sizes_down():
    books = {
        "1": book("1", (("0.55", "0.5"),)),   # half a share available
        "2": book("2", (("0.42", "0.5"),)),
    }
    # only 0.5 sets fillable; cost 0.485 -> feasible mini-purchase is allowed
    sp = plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50"))
    assert sp is not None
    assert sp.n_sets == Decimal("0.5")


def test_plan_set_purchase_no_feasible_size():
    # Best asks already sum above cap -> None
    books = {
        "1": book("1", (("0.60", "100"),)),
        "2": book("2", (("0.45", "100"),)),
    }
    assert plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50")) is None


def test_plan_set_purchase_missing_leg():
    books = {"1": book("1", (("0.55", "100"),))}
    assert plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50")) is None


def test_plan_set_purchase_empty_asks():
    books = {
        "1": book("1", ()),
        "2": book("2", (("0.42", "100"),)),
    }
    assert plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50")) is None


def test_fills_metadata():
    books = {
        "1": book("1", (("0.55", "100"),)),
        "2": book("2", (("0.42", "100"),)),
    }
    sp = plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50"))
    by_token = {f.token_id: f for f in sp.fills}
    assert by_token["1"].label == "Yes"
    assert by_token["1"].qty == sp.n_sets
    assert by_token["1"].avg_price == Decimal("0.55")
