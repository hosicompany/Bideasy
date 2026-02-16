"""
모의 투찰 테스트 시스템
======================
문제지(입찰공고) → 우리 알고리즘이 풀이 → 정답지(개찰결과)와 채점 → 성적표

흐름:
1. [문제 출제] 과거 개찰결과에서 문제지 정보만 추출
2. [풀이]     우리 recommend_bid_price() 알고리즘으로 투찰가 결정
3. [채점]     실제 예정가격/낙찰가와 비교
4. [성적표]   전체 성적 + 오답노트 출력
"""

import json
import math
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.services.calculator import CalculatorService


def load_exam_data(data_dir: Path) -> list:
    """과거 데이터(시험 문제) 로드"""
    all_data = []
    for year in range(2021, 2027):
        f = data_dir / f"opening_results_{year}.json"
        if f.exists():
            with open(f) as fh:
                items = json.load(fh)
                all_data.extend(items)
                print(f"  [{year}년] {len(items)}건 로드")
    return all_data


def split_question_and_answer(item: dict) -> tuple[dict, dict]:
    """데이터를 문제지(입찰 전 공개)와 정답지(개찰 후 공개)로 분리"""
    question = {
        "bid_no": item.get("bid_no", ""),
        "title": item.get("title", ""),
        "org": item.get("org", ""),
        "basic_price": item.get("basic_price", 0),
        "estimated_price": item.get("estimated_price", 0),
        "bid_method": item.get("bid_method", ""),
        "lower_limit_rate": item.get("lower_limit_rate", 87.745),
    }
    answer = {
        "reserved_price": item.get("reserved_price", 0),
        "winner_price": item.get("winner_price", 0),
        "winner_rate": item.get("winner_rate", 0),
    }
    return question, answer


def solve(question: dict) -> dict:
    """
    [풀이] 문제지만 보고 투찰가 결정
    우리 알고리즘(recommend_bid_price)을 호출
    """
    return CalculatorService.recommend_bid_price(
        basic_price=question["basic_price"],
        bid_method=question["bid_method"],
        contract_type="CONSTRUCTION",
        a_value=0,
    )


def grade(question: dict, our_answer: dict, real_answer: dict) -> dict:
    """
    [채점] 우리 답 vs 정답 비교
    """
    our_price = our_answer["recommended_price"]
    real_reserved = real_answer["reserved_price"]
    real_winner = real_answer["winner_price"]
    real_winner_rate = real_answer["winner_rate"]
    lower_limit_rate = question["lower_limit_rate"]
    basic_price = question["basic_price"]

    # 실제 하한선 (예정가격 기준)
    price_base = real_reserved if real_reserved > 0 else basic_price
    real_lower_limit = price_base * (lower_limit_rate / 100)

    # 하한선 통과 여부
    passed_limit = our_price >= real_lower_limit

    # 낙찰 여부 (하한선 이상 + 낙찰가 이하 = 최저가로 이김)
    won = passed_limit and our_price <= real_winner

    # 투찰률 (기초금액 대비)
    our_rate = (our_price / basic_price * 100) if basic_price > 0 else 0

    # 예정가격 예측 오차
    pred_error = 0
    if real_reserved > 0 and basic_price > 0:
        pred_error = ((basic_price - real_reserved) / real_reserved) * 100

    return {
        "passed_limit": passed_limit,
        "won": won,
        "our_price": our_price,
        "our_rate": round(our_rate, 4),
        "real_winner_price": real_winner,
        "real_winner_rate": real_winner_rate,
        "price_gap": our_price - real_winner,
        "rate_gap": round(our_rate - real_winner_rate, 4),
        "pred_error_pct": round(pred_error, 4),
        "real_lower_limit": round(real_lower_limit),
    }


def generate_report(questions, our_answers, grades, bid_methods):
    """[성적표] 전체 결과 출력"""

    total = len(grades)
    wins = sum(1 for g in grades if g["won"])
    passed = sum(1 for g in grades if g["passed_limit"])
    failed = total - passed

    print()
    print("=" * 65)
    print("  BidEasy 모의 투찰 성적표")
    print(f"  시험일: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  총 문항: {total}건")
    print("=" * 65)

    print(f"\n[ 종합 성적 ]")
    print(f"  낙찰 성공: {wins}건 / {total}건 ({wins/total*100:.1f}%)")
    print(f"  하한선 통과: {passed}건 ({passed/total*100:.1f}%)")
    print(f"  하한선 탈락: {failed}건 ({failed/total*100:.1f}%)")

    our_rates = [g["our_rate"] for g in grades]
    real_rates = [g["real_winner_rate"] for g in grades if g["real_winner_rate"] > 0]
    print(f"\n  우리 평균 투찰률: {sum(our_rates)/total:.3f}%")
    if real_rates:
        print(f"  실제 평균 낙찰률: {sum(real_rates)/len(real_rates):.3f}%")

    # 예정가격 예측 정확도
    errors = [g["pred_error_pct"] for g in grades]
    print(f"\n  예정가격 예측 오차 (기초금액 기준):")
    print(f"    평균: {sum(errors)/len(errors):+.3f}%")
    within_1 = sum(1 for e in errors if -1 <= e <= 1)
    print(f"    ±1% 이내: {within_1}건 ({within_1/len(errors)*100:.1f}%)")

    # 입찰방법별 성적
    print(f"\n[ 입찰방법별 성적 ]")
    method_groups = {}
    for i, g in enumerate(grades):
        m = bid_methods[i]
        if m not in method_groups:
            method_groups[m] = []
        method_groups[m].append(g)

    print(f"  {'입찰방법':<20} {'문항':>5} {'낙찰':>7} {'하한통과':>8} {'여유분':>6}")
    print(f"  {'-'*50}")
    for method, gs in sorted(method_groups.items(), key=lambda x: -len(x[1])):
        n = len(gs)
        w = sum(1 for g in gs if g["won"])
        p = sum(1 for g in gs if g["passed_limit"])
        margin_used = our_answers[0]["margin"]  # 같은 방법이면 같은 margin
        for i, m in enumerate(bid_methods):
            if m == method:
                margin_used = our_answers[i]["margin"]
                break
        print(f"  {method:<20} {n:>5} {w/n*100:>6.1f}% {p/n*100:>7.1f}% {margin_used:>5.1f}%p")

    # 금액대별 성적
    print(f"\n[ 금액대별 성적 ]")
    brackets = [
        ("1억 미만", 0, 1e8),
        ("1~5억", 1e8, 5e8),
        ("5~10억", 5e8, 1e9),
        ("10억 이상", 1e9, float("inf")),
    ]
    print(f"  {'금액대':<12} {'문항':>5} {'낙찰':>7} {'하한통과':>8}")
    print(f"  {'-'*35}")
    for name, lo, hi in brackets:
        gs = [grades[i] for i in range(total) if lo <= questions[i]["basic_price"] < hi]
        if gs:
            n = len(gs)
            w = sum(1 for g in gs if g["won"])
            p = sum(1 for g in gs if g["passed_limit"])
            print(f"  {name:<12} {n:>5} {w/n*100:>6.1f}% {p/n*100:>7.1f}%")

    # 오답노트: 낙찰 실패 중 아깝게 진 건 (하한 통과했지만 가격이 높았던 건)
    close_misses = []
    for i, g in enumerate(grades):
        if g["passed_limit"] and not g["won"] and g["price_gap"] > 0:
            close_misses.append((i, g["price_gap"], g["rate_gap"]))
    close_misses.sort(key=lambda x: x[1])  # 가격 차이 작은 순

    if close_misses:
        print(f"\n[ 오답노트: 아깝게 진 건 TOP 10 ]")
        print(f"  {'공사명':<30} {'우리가격':>12} {'낙찰가격':>12} {'차이':>10}")
        print(f"  {'-'*68}")
        for idx, gap, rdiff in close_misses[:10]:
            q = questions[idx]
            g = grades[idx]
            title = q["title"][:28]
            print(f"  {title:<30} {g['our_price']:>11,} {g['real_winner_price']:>11,} {gap:>+9,}")

    # 오답노트: 하한선 탈락 건 분석
    limit_fails = [(i, g) for i, g in enumerate(grades) if not g["passed_limit"]]
    if limit_fails:
        errors_fail = [g["pred_error_pct"] for _, g in limit_fails]
        print(f"\n[ 오답노트: 하한선 탈락 원인 ]")
        print(f"  탈락 건수: {len(limit_fails)}건")
        print(f"  탈락 건의 예정가격 예측 오차 평균: {sum(errors_fail)/len(errors_fail):+.3f}%")
        print(f"  → 기초금액이 예정가격보다 낮은 경우 하한선 미달 발생")
        above = sum(1 for e in errors_fail if e < 0)
        print(f"  → 기초금액 < 예정가격인 경우: {above}건 ({above/len(errors_fail)*100:.1f}%)")


def main():
    data_dir = Path(__file__).parent.parent / "data"

    print("=" * 65)
    print("  BidEasy 모의 투찰 테스트")
    print("  [문제 출제] → [풀이] → [채점] → [성적표]")
    print("=" * 65)

    # 1. 문제 로드
    print("\n[1단계] 시험 문제 로드...")
    raw_data = load_exam_data(data_dir)
    if not raw_data:
        print("  데이터 없음. 크롤링 먼저 실행하세요.")
        return

    # 유효 데이터만 (기초금액 > 0, 낙찰가 > 0, 예정가격 > 0)
    valid = [d for d in raw_data
             if d.get("basic_price", 0) > 0
             and d.get("winner_price", 0) > 0
             and d.get("reserved_price", 0) > 0]
    print(f"  전체 {len(raw_data)}건 중 유효 {len(valid)}건")

    # 2. 문제지/정답지 분리
    print("\n[2단계] 문제지와 정답지 분리...")
    questions = []
    answers = []
    for item in valid:
        q, a = split_question_and_answer(item)
        questions.append(q)
        answers.append(a)
    print(f"  문제지 {len(questions)}건 준비 완료")

    # 3. 풀이 (우리 알고리즘으로 투찰가 결정)
    print("\n[3단계] 풀이 중... (정답지 안 봄!)")
    our_answers = []
    for q in questions:
        ans = solve(q)
        our_answers.append(ans)
    print(f"  {len(our_answers)}건 풀이 완료")

    # 4. 채점
    print("\n[4단계] 채점 중...")
    grades = []
    for q, ours, real in zip(questions, our_answers, answers):
        g = grade(q, ours, real)
        grades.append(g)
    print(f"  {len(grades)}건 채점 완료")

    # 5. 성적표
    bid_methods = [q["bid_method"] for q in questions]
    generate_report(questions, our_answers, grades, bid_methods)

    # 결과 저장
    output = {
        "test_date": datetime.now().isoformat(),
        "total": len(grades),
        "wins": sum(1 for g in grades if g["won"]),
        "win_rate": round(sum(1 for g in grades if g["won"]) / len(grades) * 100, 2),
        "passed_limit": sum(1 for g in grades if g["passed_limit"]),
        "details": [
            {
                "bid_no": questions[i]["bid_no"],
                "title": questions[i]["title"],
                "bid_method": questions[i]["bid_method"],
                "basic_price": questions[i]["basic_price"],
                "our_price": grades[i]["our_price"],
                "our_rate": grades[i]["our_rate"],
                "real_winner_price": grades[i]["real_winner_price"],
                "real_winner_rate": grades[i]["real_winner_rate"],
                "won": grades[i]["won"],
                "passed_limit": grades[i]["passed_limit"],
            }
            for i in range(len(grades))
        ],
    }
    output_file = data_dir / "mock_test_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_file}")


if __name__ == "__main__":
    main()
