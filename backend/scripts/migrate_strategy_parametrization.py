"""전략 파라미터화를 `product_v1` → `ratio_pinned_v2` 로 1회 전환한다.

왜 자가보정 루프가 아니라 이 스크립트인가
--------------------------------------------
승격 가드에는 ``MAX_PARAM_JUMP = 1.0`` 이 있다. 같은 축 위에서 조금씩 움직이는
재보정을 감시하라고 둔 값인데, 파라미터화 전환은 **축 자체가 바뀌는** 일이라
adjustment 가 한 번에 최대 1.0 옮겨간다(예: 적격심사제/small −1.0 → 0.0).
그대로 주간 재보정에 맡기면 후보가 거부되고 active 는 옛 축에 머문다.

그렇다고 가드에 우회 경로를 뚫으면 다음에 누군가 그 문으로 들어온다. 그래서
전환만 루프 **밖에서** 사람이 1회 실행하고, 가드는 손대지 않는다. 전환이 끝나면
새 축이 기준선이 되므로 이후 재보정은 margin 만 움직여 가드 안에 들어온다.

무엇이 바뀌나
--------------
adjustment 를 데이터에서 적합한 사정률 중심(중앙값·부모 shrinkage)에 고정하고,
**곱을 최대한 보존하도록** margin 을 재계산한다. 곱이 보존되면 A값 없는 가격은
그대로다 — 실측에서 win·무효가 소수점 셋째 자리까지 안 움직였다(§9 ③).
A값이 있는 공고에서만 가격이 미세하게 달라진다(중앙값 5,730원). 그 차이가
바로 옛 파라미터화가 흘리던 누수이고, 이 전환이 없애려는 것이다.

사용법
------
    python scripts/migrate_strategy_parametrization.py            # 미리보기
    python scripts/migrate_strategy_parametrization.py --commit   # 실제 전환

⚠️ 배포 직후·주간 재보정(월 04:00) 이전에 실행할 것. 순서가 뒤집히면 새 축
코드가 옛 축 기준선으로 한 사이클을 돌고 가드에 거부된다(무해하지만 헛돈다).
롤백은 ``store.rollback(<이전 version_id>)``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.autocalibrate import dataset as ds
from app.services.autocalibrate import optimizer as opt
from app.services.autocalibrate.risk_model import ReservedRatioModel
from app.services.autocalibrate.strategy_store import (
    StrategyVersion,
    get_default_store,
    make_version_id,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="전략 파라미터화 1회 전환")
    parser.add_argument("--commit", action="store_true", help="실제로 새 버전을 active 로 커밋")
    parser.add_argument("--lower-rate", type=float, default=89.745,
                        help="곱 환산 기준 하한율 (기본: 10억 미만 공사)")
    args = parser.parse_args()

    store = get_default_store()
    active = store.load_active()
    if active.parametrization == opt.PARAMETRIZATION:
        print(f"이미 {opt.PARAMETRIZATION} 이다 (active={active.version_id}) — 할 일 없음")
        return 0

    records = ds.load_records()
    if not records:
        print("✗ 과거 개찰 원장이 비어 있다 — 사정률 중심을 적합할 수 없다")
        return 1

    weights = opt.adaptive_year_weights(records)
    risk_model = ReservedRatioModel.fit(records, weights)

    new_params: dict = {}
    rows: list[tuple] = []
    for method, brackets in active.params.items():
        new_params[method] = {}
        for bracket, pair in brackets.items():
            old_adj, old_margin = float(pair[0]), float(pair[1])
            new_adj = opt.pinned_adjustment(risk_model, method, bracket)
            new_margin = opt.converted_margin(
                args.lower_rate, old_adj, old_margin, new_adj
            )
            new_params[method][bracket] = [new_adj, new_margin]

            old_p = (1 + old_adj / 100) * (args.lower_rate + old_margin)
            new_p = (1 + new_adj / 100) * (args.lower_rate + new_margin)
            rows.append((f"{method}/{bracket}", old_adj, old_margin, new_adj,
                         new_margin, old_p, new_p, new_p - old_p))

    print(f"active {active.version_id} ({active.parametrization}) → {opt.PARAMETRIZATION}\n")
    print(f"{'세그먼트':<28}{'adj':>13}{'margin':>15}{'곱 변화':>12}")
    print("-" * 68)
    for name, oa, om, na, nm, op, np_, dp in rows:
        print(f"{name:<28}{oa:+.1f}→{na:+.1f}{om:>9.1f}→{nm:.1f}{dp:>+12.4f}")
    deltas = [r[7] for r in rows]
    unsafe = [r[0] for r in rows if r[7] < -1e-9]
    clamped = [r[0] for r in rows if r[4] == 0.0]
    print("-" * 68)
    print(f"곱 이탈 범위 {min(deltas):+.4f} ~ {max(deltas):+.4f} "
          f"(격자 0.1%p 잔차 — 전부 0 이상이어야 안전 방향)")
    if clamped:
        print(f"⚠️ margin 0.0 클램프(곱 보존 포기, 안전 방향): {', '.join(clamped)}")
    if unsafe:
        print(f"✗ 곱이 줄어든 세그먼트 — 무효 위험 증가: {', '.join(unsafe)}")
        return 1

    if not args.commit:
        print("\n미리보기다. 실제 전환은 --commit")
        return 0

    version = StrategyVersion(
        version_id=make_version_id(),
        created_at=datetime.now().isoformat(timespec="seconds"),
        params=new_params,
        parent_version=active.version_id,
        data_fingerprint=active.data_fingerprint,
        year_weights={str(k): v for k, v in weights.items()},
        metrics=active.metrics,
        notes=(
            f"파라미터화 전환 {active.parametrization} → {opt.PARAMETRIZATION} "
            f"(곱 보존, 이탈 {min(deltas):+.4f}~{max(deltas):+.4f} 전부 안전 방향"
            f"{', 클램프 ' + ','.join(clamped) if clamped else ''}). "
            "사람 1회 실행 · 자가보정 루프 밖. "
            "adjustment 를 이전 버전과 같은 축에서 비교하지 말 것."
        ),
        parametrization=opt.PARAMETRIZATION,
    )
    store.commit(version)
    from app.services.calculator import reload_strategy_cache

    reload_strategy_cache()
    print(f"\n✓ 커밋 완료 — active = {version.version_id}")
    print(f"  롤백: store.rollback('{active.version_id}')")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
