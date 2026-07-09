"""Fake `polymarket` binary for tests. FAKE_MODE selects canned behavior."""
import json
import os
import sys

MODE = os.environ.get("FAKE_MODE", "ok")

BOOK_255 = {
    "market": "0xabc", "asset_id": "255",
    "asks": [{"price": "0.99", "size": "100"}, {"price": "0.55", "size": "10"}],
    "bids": [{"price": "0.50", "size": "20"}],
}
BOOK_256 = {
    "market": "0xabc", "asset_id": "256",
    "asks": [{"price": "0.42", "size": "30"}],
    "bids": [{"price": "0.40", "size": "15"}],
}


def main() -> int:
    args = sys.argv[1:]
    # The wrapper always prepends the global `-o json` flag; strip it before routing.
    if args[:2] == ["-o", "json"]:
        args = args[2:]
    if MODE == "error_json":
        print(json.dumps({"error": "Status: error(404 Not Found)"}))
        return 1
    if MODE == "error_exit_only":
        print(json.dumps({"anything": True}))
        return 1
    if MODE == "bad_json":
        print("this is not json")
        return 0
    if MODE == "hang":
        import time
        time.sleep(60)
        return 0

    # MODE == "ok": route by subcommand
    if args[:2] == ["markets", "get"]:
        print(json.dumps({"id": "540817", "question": "Q?", "slug": args[2]}))
    elif args[:2] == ["events", "get"]:
        print(json.dumps({"id": args[2], "title": "E", "negRisk": True, "markets": []}))
    elif args[:2] == ["clob", "books"]:
        ids = [t.strip() for t in args[2].split(",")]
        out = []
        if "255" in ids or "0xff" in ids:
            out.append(BOOK_255)
        if "256" in ids:
            out.append(BOOK_256)
        print(json.dumps(out))
    elif args[:2] == ["clob", "midpoints"]:
        print(json.dumps({"255": "0.525", "256": "0.41"}))
    else:
        print(json.dumps({"error": f"unknown args {args}"}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
