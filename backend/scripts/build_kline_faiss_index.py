from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent.kline_faiss_store import build_and_persist_index  # noqa: E402
from app.modules.fund_offline.service import ensure_offline_schema  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build FAISS index from offline NAV snapshots.")
    parser.add_argument("--max-codes", type=int, default=None, help="Limit code count for build.")
    args = parser.parse_args()
    ensure_offline_schema()
    result = build_and_persist_index(max_codes=args.max_codes)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
