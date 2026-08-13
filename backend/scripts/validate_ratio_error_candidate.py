"""사정률 예측 후보를 autocalibrate 과거 원장으로 walk-forward 검증한다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.autocalibrate import dataset as ds
from app.services.autocalibrate.ratio_error import walk_forward_validate
from app.services.autocalibrate.strategy_store import get_default_store


def main() -> int:
    parser = argparse.ArgumentParser(
        description="사정률 예측 후보 expanding walk-forward 검증"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="선택 시 JSON 결과 저장 경로",
    )
    args = parser.parse_args()

    records = ds.load_records(year_range=(2021, 2026), db=None)
    active = get_default_store().load_active()
    report = walk_forward_validate(records, active.params)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if report["selected_shadow_candidate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
