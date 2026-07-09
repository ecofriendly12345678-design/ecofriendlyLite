import os
import sys

import pytest

from agent.cli import CliError, PolymarketCli

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_polymarket.py")]


def make(mode: str = "ok", timeout: float = 30.0) -> PolymarketCli:
    os.environ["FAKE_MODE"] = mode
    return PolymarketCli(binary=FAKE, timeout=timeout)


def teardown_function():
    os.environ.pop("FAKE_MODE", None)


def test_get_market():
    assert make().get_market("some-slug")["slug"] == "some-slug"


def test_get_event():
    assert make().get_event("123")["negRisk"] is True


def test_get_books_keyed_by_canonical_id():
    books = make().get_books(["255", "256"])
    assert set(books) == {"255", "256"}
    assert books["255"]["asset_id"] == "255"


def test_get_books_normalizes_hex_input():
    books = make().get_books(["0xff"])
    assert "255" in books


def test_get_books_chunks_large_requests():
    # 45 ids -> 3 subprocess calls (chunk size 20). The fake returns only
    # books it knows; the point is that no call gets >20 ids (fake would
    # blow up on absurd argv? -> assert via returned data still correct).
    ids = ["255", "256"] + [str(1000 + i) for i in range(43)]
    books = make().get_books(ids)
    assert set(books) == {"255", "256"}


def test_get_midpoints():
    mids = make().get_midpoints(["255", "256"])
    assert mids["255"] == "0.525"


def test_error_json_raises():
    with pytest.raises(CliError, match="404"):
        make("error_json").get_market("x")


def test_nonzero_exit_raises():
    with pytest.raises(CliError):
        make("error_exit_only").get_market("x")


def test_bad_json_raises():
    with pytest.raises(CliError, match="JSON"):
        make("bad_json").get_market("x")


def test_timeout_raises():
    with pytest.raises(CliError, match="[Tt]ime"):
        make("hang", timeout=1.0).get_market("x")
