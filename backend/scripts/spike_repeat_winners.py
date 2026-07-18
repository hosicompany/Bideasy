"""
반복낙찰(들러리/독과점 신호) 타당성 스파이크 — 안전망 레이어 ④ 결정 게이트
==========================================================================
질문: "이 공고, 매년 같은 업체가 가져간다" 경보가 의미 있을 만큼
반복 패턴 공고가 흔한가?

사전 등록 킬 기준 (docs/COMPETITIVE_STRATEGY.md §6, 2026-07-17 동결):
  "OpeningResult 로 '동일 낙찰자 반복 공고' 비율 1일 스파이크 분석 —
   반복 패턴 공고 5% 미만이면 ④ 폐기."

방법 (보수적 → 관대 순 3지표):
  A. 연례 반복 그룹  = (발주기관, 정규화 제목) 이 서로 다른 연도에 2회+ 등장
  B. 그중 동일 낙찰자 = A 그룹에서 같은 업체가 2회+ 낙찰 (경보 대상의 핵심)
  C. 기관 단골 낙찰   = (발주기관, 낙찰업체) 조합이 3회+ (제목 무관, 관대 상한)

정규화: 숫자·연도·차수·공백·괄호 제거 — 제목 표기 흔들림에 보수적
(과소집계 방향 → 게이트 판정이 낙관 오류를 범하지 않게).

실행: cd backend && python scripts/spike_repeat_winners.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_PATH = DATA_DIR / "spike_repeat_winners_results.json"
KILL_THRESHOLD_PCT = 5.0  # 사전 등록 킬 기준


_NORM_RE = re.compile(r"[0-9]|\s|[()\[\]{}·.,\-_/]|년도?|차수?|제|호")


def norm_title(title: str) -> str:
    """숫자·연도·차수·공백·구두점 제거 — 연례 공고의 표기 흔들림 흡수."""
    return _NORM_RE.sub("", title or "")


class Rec:
    """스파이크 전용 경량 레코드 — BidRecord 엔 winner_company 가 없어 원본 JSON 직접 로드."""

    __slots__ = ("org", "title", "winner_company", "year")

    def __init__(self, org, title, winner_company, year):
        self.org = org
        self.title = title
        self.winner_company = winner_company
        self.year = year


def load_raw() -> list[Rec]:
    out: list[Rec] = []
    seen: set[str] = set()
    for year in range(2021, 2027):
        f = DATA_DIR / f"opening_results_{year}.json"
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fh:
            items = json.load(fh)
        for item in items:
            org = item.get("org") or ""
            winner = item.get("winner_company") or ""
            title = item.get("title") or ""
            bid_no = item.get("bid_no") or ""
            if not org or not winner or not title:
                continue
            if bid_no and bid_no in seen:  # 재입찰 차수 중복 방지
                continue
            seen.add(bid_no)
            od = item.get("open_date", "")
            y = int(od[:4]) if od[:4].isdigit() else year
            out.append(Rec(org, title, winner, y))
    return out


def main() -> None:
    records = load_raw()
    n = len(records)
    print(f"반복낙찰 스파이크 — 유효 레코드 {n}건 (기관·낙찰자·제목 존재)")

    # ── A. 연례 반복 그룹: (기관, 정규화 제목) 2회+ & 2개 연도+ ──
    groups: dict[tuple, list] = defaultdict(list)
    for r in records:
        key = (r.org, norm_title(r.title))
        if key[1]:  # 정규화 후 빈 제목 제외
            groups[key].append(r)

    repeat_groups = {
        k: v for k, v in groups.items()
        if len(v) >= 2 and len({r.year for r in v}) >= 2
    }
    notices_in_repeat = sum(len(v) for v in repeat_groups.values())

    # ── B. 그중 동일 낙찰자 반복 (경보 대상) ──
    same_winner_groups = {}
    for k, v in repeat_groups.items():
        winner_counts: dict[str, int] = defaultdict(int)
        for r in v:
            winner_counts[r.winner_company] += 1
        top_winner, top_cnt = max(winner_counts.items(), key=lambda kv: kv[1])
        if top_cnt >= 2:
            same_winner_groups[k] = {
                "n_notices": len(v),
                "years": sorted({r.year for r in v}),
                "top_winner": top_winner,
                "top_winner_wins": top_cnt,
                "monopoly": top_cnt == len(v),  # 전부 같은 업체
            }
    notices_alertable = sum(g["n_notices"] for g in same_winner_groups.values())
    monopoly_notices = sum(
        g["n_notices"] for g in same_winner_groups.values() if g["monopoly"]
    )

    # ── C. 기관 단골 낙찰 (제목 무관, 관대 상한) ──
    org_winner: dict[tuple, int] = defaultdict(int)
    for r in records:
        org_winner[(r.org, r.winner_company)] += 1
    frequent_pairs = {k: c for k, c in org_winner.items() if c >= 3}
    notices_frequent_pair = sum(frequent_pairs.values())

    pct_repeat = notices_in_repeat / n * 100 if n else 0.0
    pct_alertable = notices_alertable / n * 100 if n else 0.0
    pct_monopoly = monopoly_notices / n * 100 if n else 0.0
    pct_frequent = notices_frequent_pair / n * 100 if n else 0.0

    print(f"\nA. 연례 반복 공고(기관×제목, 2회+·2연도+): {notices_in_repeat}건 "
          f"= {pct_repeat:.2f}%  (그룹 {len(repeat_groups)}개)")
    print(f"B. 그중 동일 낙찰자 2회+(경보 대상):      {notices_alertable}건 "
          f"= {pct_alertable:.2f}%  (그룹 {len(same_winner_groups)}개)")
    print(f"   └ 완전 독점(전 회차 동일 업체):        {monopoly_notices}건 = {pct_monopoly:.2f}%")
    print(f"C. 기관 단골(기관×업체 3회+, 제목 무관):  {notices_frequent_pair}건 = {pct_frequent:.2f}%")

    # 상위 사례 (검증용 표본)
    top_cases = sorted(
        same_winner_groups.items(), key=lambda kv: -kv[1]["top_winner_wins"]
    )[:10]
    if top_cases:
        print("\n동일 낙찰자 반복 상위 사례:")
        for (org, _t), g in top_cases:
            print(f"  {org} | {g['years']} | {g['top_winner']} "
                  f"{g['top_winner_wins']}/{g['n_notices']}회")

    # ── 게이트 판정 (사전 등록: 경보 대상 B 기준) ──
    verdict = "KEEP" if pct_alertable >= KILL_THRESHOLD_PCT else "KILL"
    print(f"\n게이트 판정: 경보 대상 {pct_alertable:.2f}% vs 킬 기준 {KILL_THRESHOLD_PCT}% "
          f"→ {'✅ 유지(KEEP) — 안전망 ④ 진행 가능' if verdict == 'KEEP' else '❌ 폐기(KILL) — 안전망 ④ 보류'}")

    RESULTS_PATH.write_text(json.dumps({
        "n_records": n,
        "kill_threshold_pct": KILL_THRESHOLD_PCT,
        "A_repeat_notices": notices_in_repeat,
        "A_repeat_pct": round(pct_repeat, 2),
        "B_alertable_notices": notices_alertable,
        "B_alertable_pct": round(pct_alertable, 2),
        "B_monopoly_pct": round(pct_monopoly, 2),
        "C_frequent_pair_pct": round(pct_frequent, 2),
        "verdict": verdict,
        "top_cases": [
            {"org": org, "years": g["years"], "winner": g["top_winner"],
             "wins": g["top_winner_wins"], "n": g["n_notices"]}
            for (org, _t), g in top_cases
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과 저장: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
