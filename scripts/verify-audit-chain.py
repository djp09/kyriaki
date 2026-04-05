#!/usr/bin/env python3
"""Verify the integrity of the PHI audit log hash chain.

Usage:
    python scripts/verify-audit-chain.py

Exit codes:
    0 — chain intact
    1 — chain broken (prints offending rows)
    2 — error opening/reading database

Run regularly (nightly) and after any suspected tamper event. See ADR-004.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running from repo root: add backend/ to path.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))


async def _main() -> int:
    try:
        from database import async_session
        from phi.audit import verify_chain
    except Exception as e:  # pragma: no cover
        print(f"ERROR: could not import backend modules: {e}", file=sys.stderr)
        return 2

    try:
        async with async_session() as session:
            ok, errors = await verify_chain(session)
    except Exception as e:  # pragma: no cover
        print(f"ERROR: database read failed: {e}", file=sys.stderr)
        return 2

    if ok:
        print("OK: audit log chain intact.")
        return 0

    print(f"FAIL: audit log chain broken ({len(errors)} issues):", file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
