from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.modules.fund_offline.service import ensure_offline_schema, sync_fund_nav_snapshot  # noqa: E402
from app.modules.fund_offline.session import OfflineSessionLocal  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync fund NAV snapshot into offline sqlite warehouse.")
    parser.add_argument("--full", action="store_true", help="Run full-range sync.")
    parser.add_argument("--incremental", action="store_true", help="Run incremental sync explicitly.")
    parser.add_argument("--max-codes", type=int, default=None, help="Limit catalog codes for current run.")
    parser.add_argument("--no-index", action="store_true", help="Skip rebuilding FAISS index after sync.")
    parser.add_argument("--progress-every", type=int, default=10, help="Print progress every N codes.")
    args = parser.parse_args()

    ensure_offline_schema()
    db = OfflineSessionLocal()
    try:
        run_full = bool(args.full) and not bool(args.incremental)
        progress_every = max(1, int(args.progress_every))

        def _on_progress(evt: dict[str, object]) -> None:
            stage = str(evt.get("stage") or "running")
            done = int(evt.get("codes_processed") or 0)
            total = int(evt.get("codes_total") or 0)
            rows = int(evt.get("rows_upserted") or 0)
            elapsed = float(evt.get("elapsed_sec") or 0.0)
            now = datetime.now().strftime("%H:%M:%S")
            if stage == "error":
                err = str(evt.get("error") or "unknown")
                print(
                    f"[{now}] [offline-sync] ERROR done={done}/{total} rows={rows} elapsed={elapsed:.1f}s err={err}",
                    flush=True,
                )
                return
            if stage == "done":
                print(
                    f"[{now}] [offline-sync] DONE done={done}/{total} rows={rows} elapsed={elapsed:.1f}s",
                    flush=True,
                )
                return
            if stage == "start":
                print(
                    f"[{now}] [offline-sync] START total_codes={total} full={run_full} rebuild_index={not bool(args.no_index)}",
                    flush=True,
                )
                return
            last_code = str(evt.get("last_code") or "")
            tail = f" last_code={last_code}" if last_code else ""
            print(
                f"[{now}] [offline-sync] RUNNING done={done}/{total} rows={rows} elapsed={elapsed:.1f}s{tail}",
                flush=True,
            )

        result = sync_fund_nav_snapshot(
            db,
            full=run_full,
            max_codes=args.max_codes,
            rebuild_index=not bool(args.no_index),
            progress_every=progress_every,
            progress_callback=_on_progress,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
