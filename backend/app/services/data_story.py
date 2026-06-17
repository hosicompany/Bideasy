"""Track B 데이터 스토리 — 개찰 데이터(OpeningResult)로 주간 글 초안 자동 생성.

설계 원칙: **숫자는 DB에서 결정적으로 계산(환각 차단), 서술(인트로·인사이트)만 LLM이 감싼다.**
결과는 status=draft / source=auto 로 만들어 사람이 /admin-blog 에서 1클릭 발행.

`build_weekly_story(db, ref)` — 지난주 데이터로 글 dict 조립 (숫자 결정적).
`create_weekly_draft(db, ref)` — 위 결과로 BlogPost 초안 생성 (멱등: 같은 주 slug 있으면 skip).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.db import models
from app.services import blog as blog_svc

logger = get_logger(__name__)

LOW_COMP_THRESHOLD = 2  # 참여업체 이하 = 단독·저경쟁 "기회"


# ─── 주(週) 계산 ──────────────────────────────────────────────

def iso_week_slug(d: date) -> str:
    iso = d.isocalendar()
    return f"weekly-{iso[0]}-w{iso[1]:02d}"


def last_completed_week(ref: date) -> tuple:
    """ref 기준 직전 '완료된' 주(월~일)."""
    this_monday = ref - timedelta(days=ref.weekday())
    last_monday = this_monday - timedelta(days=7)
    return last_monday, last_monday + timedelta(days=6)


# ─── 포맷 헬퍼 ────────────────────────────────────────────────

def _fmt_rate(r) -> str:
    return f"{r:.3f}%" if r else "—"


def _fmt_eok(p) -> str:
    return f"{p / 1e8:.1f}억" if p else "—"


def _fmt_cnt(n) -> str:
    return f"{int(n)}개사" if n else "—"


# ─── 데이터 수집 (결정적) ──────────────────────────────────────

def _collect(db, start: datetime, end: datetime) -> list:
    """[start, end) 구간 개찰결과 + (있으면) 공고 제목 조인."""
    rows = (
        db.query(models.OpeningResult, models.Notice.title)
        .outerjoin(models.Notice, models.Notice.bid_no == models.OpeningResult.bid_no)
        .filter(
            models.OpeningResult.open_date >= start,
            models.OpeningResult.open_date < end,
            models.OpeningResult.participants_count.isnot(None),
        )
        .all()
    )
    out = []
    for r, title in rows:
        out.append({
            "bid_no": r.bid_no,
            "title": title or f"{r.organization or '공고'} ({r.bid_no})",
            "org": r.organization or "—",
            "participants": r.participants_count or 0,
            "rate": r.winner_rate,
            "basic_price": r.basic_price,
        })
    return out


# ─── LLM 서술 (인트로·인사이트만, 숫자는 안 만짐) ─────────────────

def _llm_narrative(ctx: str) -> Optional[dict]:
    """주어진 통계로 인트로·인사이트 프로즈 생성. 키 없거나 실패 시 None(→ 템플릿 폴백)."""
    if not getattr(settings, "OPENAI_API_KEY", ""):
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        sys = (
            "너는 공공입찰 데이터 매체 'BidEasy'의 에디터다. 주어진 통계 '숫자만' 근거로 "
            "쉽고 신뢰감 있게 쓴다. 새로운 숫자나 사실을 지어내지 마라. 과장·낚시 금지. "
            'JSON {"intro": "...", "insight": "..."} 으로만 답하라. '
            "intro=2~3문장 도입, insight=2문장 인사이트(중소 시공사 대표 독자 대상)."
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": ctx}],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=500,
        )
        data = json.loads(resp.choices[0].message.content)
        intro, insight = (data.get("intro") or "").strip(), (data.get("insight") or "").strip()
        if intro and insight:
            return {"intro": intro, "insight": insight}
    except Exception as e:
        logger.warning(f"data_story LLM narrative failed: {e}")
    return None


# ─── 글 조립 ──────────────────────────────────────────────────

def build_weekly_story(db, ref_date: Optional[date] = None) -> Optional[dict]:
    """지난주 데이터로 글 dict 조립. 데이터 없으면 None."""
    ref = ref_date or date.today()
    mon, sun = last_completed_week(ref)
    start = datetime(mon.year, mon.month, mon.day)
    end = start + timedelta(days=7)
    rows = _collect(db, start, end)
    if not rows:
        return None

    top = sorted(rows, key=lambda x: x["participants"], reverse=True)[:10]
    opps = sorted(
        [r for r in rows if r["participants"] and r["participants"] <= LOW_COMP_THRESHOLD],
        key=lambda x: (x["basic_price"] or 0), reverse=True,
    )[:10]
    n = len(rows)
    hottest = top[0] if top else None
    rates = [r["rate"] for r in rows if r["rate"]]
    avg_rate = sum(rates) / len(rates) if rates else None

    period = f"{mon.month:02d}.{mon.day:02d}~{sun.month:02d}.{sun.day:02d}"
    period_long = f"{mon.month}월 {mon.day}일~{sun.month}월 {sun.day}일"

    parts = [f"기간 {mon.isoformat()}~{sun.isoformat()}.", f"집계 공고 {n}건."]
    if hottest:
        parts.append(f"최고 경쟁: '{hottest['title']}' {hottest['participants']}개사.")
    parts.append(f"단독·저경쟁({LOW_COMP_THRESHOLD}개사 이하) {len(opps)}건.")
    if avg_rate:
        parts.append(f"평균 낙찰률 {avg_rate:.2f}%.")
    ctx = " ".join(parts)

    narr = _llm_narrative(ctx) or {
        "intro": (
            f"지난주({period_long}) 나라장터 개찰 결과를 모았습니다. 집계된 {n}건 가운데 "
            "경쟁이 가장 치열했던 공고와, 반대로 경쟁이 거의 없었던 '기회' 공고를 정리했어요."
        ),
        "insight": (
            "경쟁률이 높은 공고일수록 하한선 부근 1원 싸움이 됩니다. 반대로 단독·저경쟁 공고는 "
            "자격만 맞으면 무혈입성에 가까운 기회예요 — 어디에 힘을 줄지 두 정보를 같이 보면 보입니다."
        ),
    }

    L = [narr["intro"], ""]
    L.append(
        f"> **30초 요약** — 지난주 개찰 {n}건. 최다 경쟁 "
        f"{(str(hottest['participants']) + '개사') if hottest else '—'}"
        f"{(' (' + hottest['title'] + ')') if hottest else ''}, "
        f"단독·저경쟁 기회 {len(opps)}건."
    )
    L += ["", "## 가장 치열했던 공고 TOP10", "", "| 순위 | 공고 | 발주처 | 참여 | 낙찰률 |", "|---|---|---|---|---|"]
    for i, r in enumerate(top, 1):
        L.append(f"| {i} | {r['title']} | {r['org']} | {_fmt_cnt(r['participants'])} | {_fmt_rate(r['rate'])} |")
    if opps:
        L += ["", "## 단독·저경쟁 '기회' 공고", "",
              f"참여 {LOW_COMP_THRESHOLD}개사 이하 — 자격만 맞으면 노려볼 만했던 공고입니다.",
              "", "| 공고 | 발주처 | 참여 | 기초금액 |", "|---|---|---|---|"]
        for r in opps:
            L.append(f"| {r['title']} | {r['org']} | {_fmt_cnt(r['participants'])} | {_fmt_eok(r['basic_price'])} |")
    L += ["", "## 이번 주 인사이트", "", narr["insight"], "", "---", "",
          "보고 있는 공고가 있다면 [공고 검색](/search)에서 기초금액·A값까지 확인하고, "
          "[투찰가 계산기](/calculator)로 안전 투찰가를 1원 단위까지 계산해보세요. 회원가입 없이 무료입니다."]

    return {
        "slug": iso_week_slug(mon),
        "title": f"지난주 입찰 결산 — 치열했던 TOP10 & 단독·저경쟁 기회 ({period})",
        "summary": f"지난주({period}) 개찰 {n}건 — 가장 치열했던 공고 TOP10과 단독·저경쟁 기회 공고를 데이터로 정리했습니다.",
        "category": "데이터 스토리",
        "tags": "데이터스토리, 개찰결과, 경쟁률, 단독응찰",
        "body_md": "\n".join(L),
        "period": {"start": mon.isoformat(), "end": sun.isoformat(), "count": n, "opportunities": len(opps)},
    }


def create_weekly_draft(db, ref_date: Optional[date] = None):
    """주간 데이터스토리 초안 생성. 반환 (post|None, status).

    status: created | exists | no_data
    멱등 — 같은 주 slug 가 파일/DB 에 이미 있으면 생성 안 함.
    """
    story = build_weekly_story(db, ref_date)
    if not story:
        return None, "no_data"
    if blog_svc.get_post(story["slug"], db) is not None:
        existing = db.query(models.BlogPost).filter(models.BlogPost.slug == story["slug"]).first()
        return existing, "exists"
    html, rt = blog_svc.render(story["body_md"])
    post = models.BlogPost(
        slug=story["slug"],
        title=story["title"],
        summary=story["summary"],
        category=story["category"],
        tags=story["tags"],
        body_md=story["body_md"],
        body_html=html,
        reading_time=rt,
        status="draft",
        source="auto",
        date="",
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post, "created"
