"""The ONLY module allowed to talk to the `polymarket` binary (read-only subcommands).

Read-only invariant: this wrapper exposes exactly: markets get, events get,
clob books, clob midpoints — nothing that signs, spends, or transacts.
(Word choice in this file is constrained by tests/test_safety.py.)
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from agent.models import normalize_token_id

_CHUNK = 20  # max token ids per batch call


class CliError(Exception):
    def __init__(self, message: str, argv: list[str]):
        super().__init__(f"{message} (argv: {' '.join(argv)})")
        self.message = message
        self.argv = argv


class PolymarketCli:
    def __init__(self, binary: str | list[str] = "polymarket", timeout: float = 30.0):
        self._binary = [binary] if isinstance(binary, str) else list(binary)
        self._timeout = timeout

    def _run(self, *args: str) -> Any:
        argv = [*self._binary, "-o", "json", *args]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=self._timeout
            )
        except subprocess.TimeoutExpired:
            raise CliError(f"Timed out after {self._timeout}s", argv) from None
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise CliError(
                f"Invalid JSON from CLI (exit={proc.returncode}): "
                f"{proc.stdout[:200]!r} stderr={proc.stderr[:200]!r}", argv
            ) from None
        if isinstance(data, dict) and "error" in data:
            raise CliError(str(data["error"]), argv)
        if proc.returncode != 0:
            raise CliError(f"CLI exited {proc.returncode}", argv)
        return data

    def get_market(self, ref: str) -> dict:
        return self._run("markets", "get", ref)

    def get_event(self, ref: str) -> dict:
        return self._run("events", "get", ref)

    def get_books(self, token_ids: list[str]) -> dict[str, dict]:
        """Books keyed by canonical token id. One bad token can poison a whole
        batched `clob books` call, so on a chunk failure we retry that chunk's
        tokens individually and skip only the ones that genuinely error —
        the caller (scanner/MTM) already tolerates missing books."""
        out: dict[str, dict] = {}
        for i in range(0, len(token_ids), _CHUNK):
            chunk = token_ids[i : i + _CHUNK]
            try:
                result = self._run("clob", "books", ",".join(chunk))
            except CliError:
                for tid in chunk:
                    try:
                        book = self._run("clob", "book", tid)
                    except CliError as e:
                        print(f"warn: no book for token {tid[:16]}…: {e.message[:80]}")
                        continue
                    out[normalize_token_id(book["asset_id"])] = book
                continue
            for book in result:
                out[normalize_token_id(book["asset_id"])] = book
        return out

    def get_midpoints(self, token_ids: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(0, len(token_ids), _CHUNK):
            chunk = token_ids[i : i + _CHUNK]
            result = self._run("clob", "midpoints", ",".join(chunk))
            for tid, mid in result.items():
                out[normalize_token_id(tid)] = mid
        return out
