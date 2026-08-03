"""과거 데이터 5-arm 백테스트 CLI — 로직은 app/services/arm_backtest.py.

화면(어드민 🧪 백테스트 탭)과 CLI 가 같은 코드를 쓰게 해서, 두 곳이 다른
수치를 내는 일이 없게 한다.

실행: cd backend && python scripts/backtest_arms.py
출력: data/backtest_arms_results.json (+ 콘솔 표)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from app.services import arm_backtest as ab  # noqa: E402

_OUT = Path(__file__).resolve().parent.parent / "data" / "backtest_arms_results.json"


def main() -> int:
    res = ab.run()
    if not res.get("available"):
        print(res.get("reason", "데이터 없음"))
        return 1

    excluded = res.get("n_excluded_base_mismatch", 0)
    print(f"레코드 {res['n_records']}건 · 슬라이스 {res['slice_sizes']}")
    if excluded:
        print(f"⚠️ 금액 기준 불일치 {excluded}건 제외 (불러온 {res['n_loaded']}건 중)")

    def row(name: str, m: dict) -> str:
        return (f"  {name:14s} 무효 {m['dropout_rate']:6.2f}%  "
                f"적중 {m['win_rate']:6.2f}% "
                f"(CI {m['win_ci95'][0]:5.1f}~{m['win_ci95'][1]:5.1f})  n={m['n']}")

    for key, title in (
        ("overall", "전체 (frontier 는 자기 학습분 포함 — 편향)"),
        ("holdout", "holdout 2025 (공정 비교)"),
        ("qualification_holdout", "적격심사제 · holdout 2025 (비치헤드)"),
    ):
        print(f"\n=== {title} ===")
        for name, e in res["arms"].items():
            if key in e:
                print(row(name, e[key]))

    print("\n주의:")
    for c in res["caveats"]:
        print(f"  - {c}")

    _OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
