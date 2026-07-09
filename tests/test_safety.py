"""Structural read-only guarantee: the agent can never place a real order.

Two invariants:
1. Only cli.py may import subprocess (it is the single gateway to the binary).
2. cli.py must not contain any trading/wallet/on-chain subcommand string.
"""
import pathlib
import re

SRC = pathlib.Path(__file__).parent.parent / "src" / "agent"

FORBIDDEN_IN_CLI = [
    "create-order", "market-order", "post-orders", "cancel",
    "approve", "ctf", "wallet", "bridge", "create-api-key",
    "delete-api-key", "update-balance",
]


def test_only_cli_module_uses_subprocess():
    offenders = []
    for path in SRC.glob("*.py"):
        if path.name == "cli.py":
            continue
        text = path.read_text()
        if re.search(r"^\s*(import subprocess|from subprocess)", text, re.M):
            offenders.append(path.name)
    assert offenders == [], f"subprocess outside cli.py: {offenders}"


def test_cli_module_has_no_write_subcommands():
    text = (SRC / "cli.py").read_text()
    hits = [w for w in FORBIDDEN_IN_CLI if w in text]
    assert hits == [], f"forbidden subcommand strings in cli.py: {hits}"
