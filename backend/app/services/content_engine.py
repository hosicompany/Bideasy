"""
콘텐츠 엔진 Phase 1 — 주제 큐 → 구조화 정본(블록) → 검수 대기 초안
====================================================================
docs/CONTENT_ENGINE.md §2·§7 Phase 1 구현.

원칙:
- **블록이 원본** — body_md 는 블록에서 결정적으로 렌더된 파생(채널 정합의 근원).
- **검수 게이트** — 지식(K)·상록수(A) 트랙은 publish_at 없이 draft 저장,
  사람이 승인/예약해야 발행(§5). 데이터스토리(B)만 유예 자동발행.
- **정직** — LLM 에 숫자·통계 지어내기 금지 명시. data_blocks 는 우리 DB 숫자가
  있을 때만(K 트랙 기본 생성에서는 비움). '낙찰률' 마케팅 표현 금지.
- OPENAI_API_KEY 미설정이면 지어낸 폴백 초안을 만들지 않고 명시적 실패.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.core.config import settings
from app.db import models
from app.services import blog as blog_svc

logger = logging.getLogger(__name__)

# ─── 통합 주제 큐 (Track K 시드 24 — docs/CONTENT_ENGINE.md §4에서 실체화) ───
# 캘린더 문서(docs/CONTENT_CALENDAR.md §Track K)가 사람용 정본, 이 리스트가 코드용 실체.
TOPIC_SEEDS: list[dict] = [
    {"code": "K1", "title": "100개사가 몰려도 낙찰이 '실력'이 아닌 이유", "angle": "예측 환상 깨기(사정률 추첨)", "keyword": "사정률 추첨", "priority": "P1"},
    {"code": "K2", "title": "낙찰과 탈락을 가른 1원 — 실제 개찰 사례", "angle": "1원 정밀", "keyword": "입찰 1원 차이", "priority": "P1"},
    {"code": "K3", "title": "옆 동네 업체는 왜 이 공고 못 넣나 (지역제한 3분)", "angle": "자격필터", "keyword": "지역제한 입찰", "priority": "P1"},
    {"code": "K4", "title": "전기공사 면허로 넣는 공고 vs 못 넣는 공고", "angle": "자격필터", "keyword": "전기공사 입찰 면허", "priority": "P1"},
    {"code": "K5", "title": "A값 하나 빠뜨려 적자 수주한 사장님 이야기", "angle": "A값·적자 함정", "keyword": "A값 계산", "priority": "P1"},
    {"code": "K6", "title": "아무도 안 넣은 공고 — 왜 비었고 어떻게 찾나", "angle": "단독·저경쟁 기회", "keyword": "단독응찰 공고", "priority": "P1"},
    {"code": "K7", "title": "낙찰받고도 손해 보는 문구 — 독소조항 실전 3선", "angle": "독소조항", "keyword": "입찰 독소조항", "priority": "P1"},
    {"code": "K8", "title": "서류 하나 빠져 탈락 — 적격심사 흔한 실수 5", "angle": "흔한 실수", "keyword": "적격심사 서류", "priority": "P1"},
    {"code": "K9", "title": "'예측·적중률' 광고를 믿으면 안 되는 이유", "angle": "정직 포지션", "keyword": "낙찰가 예측", "priority": "P2"},
    {"code": "K10", "title": "낙찰하한선 바로 위 1원 싸움, 실제로 얼마나 붙나", "angle": "데이터 스낵", "keyword": "낙찰하한선", "priority": "P2"},
    {"code": "K11", "title": "기초금액·예정가격·사정률, 3분 안에 구분하기", "angle": "용어 오해", "keyword": "예정가격 기초금액", "priority": "P2"},
    {"code": "K12", "title": "지난달 최다 경쟁 공고는 몇 개사였을까", "angle": "데이터 스낵(월간)", "keyword": "", "priority": "P2"},
    {"code": "K13", "title": "소액수의 vs 적격심사, 뭐부터 노려야 하나", "angle": "전략 팁", "keyword": "소액수의계약", "priority": "P2"},
    {"code": "K14", "title": "입찰보증금, 돌려받는 것과 떼이는 것", "angle": "절차 오해", "keyword": "입찰보증금", "priority": "P2"},
    {"code": "K15", "title": "지체상금 폭탄 — 하루 늦으면 얼마인가", "angle": "계약 리스크", "keyword": "지체상금 계산", "priority": "P2"},
    {"code": "K16", "title": "같은 공고인데 왜 내 점수만 낮을까 (이행능력)", "angle": "적격심사 오해", "keyword": "적격심사 점수", "priority": "P2"},
    {"code": "K17", "title": "공동수급체, 언제 이득이고 언제 독인가", "angle": "전략 팁", "keyword": "공동수급체", "priority": "P3"},
    {"code": "K18", "title": "부정당업자 제재 — 한 번 걸리면 얼마나 막히나", "angle": "리스크 경고", "keyword": "부정당업자", "priority": "P3"},
    {"code": "K19", "title": "개찰 결과에서 다음 입찰 힌트 읽는 법", "angle": "데이터 활용", "keyword": "개찰결과 분석", "priority": "P3"},
    {"code": "K20", "title": "나라장터 인증서·지문 등록, 처음이면 여기서 막힌다", "angle": "입문 장벽", "keyword": "나라장터 지문등록", "priority": "P3"},
    {"code": "K21", "title": "물가변동·설계변경 대금조정, 손해 안 보려면", "angle": "계약 실무", "keyword": "물가변동 대금조정", "priority": "P3"},
    {"code": "K22", "title": "'재공고'는 왜 뜨고, 나에겐 기회일까", "angle": "기회 포착", "keyword": "재공고 입찰", "priority": "P3"},
    {"code": "K23", "title": "최저가 vs 적격심사 — 왜 무작정 싸게 쓰면 지나", "angle": "전략 오해", "keyword": "적격심사 최저가", "priority": "P3"},
    {"code": "K24", "title": "연말 예산 소진철, 공고가 쏟아지는 이유", "angle": "시즌 인사이트", "keyword": "연말 관급공사", "priority": "P3"},
]

_DEFAULT_LINKS = ["/calculator", "/diagnose", "/search"]
_DEFAULT_CTA = (
    "공고가 눈에 들어왔다면 [무료 자격 진단](/diagnose)으로 참여 가능 여부부터 확인하고, "
    "[투찰가 계산기](/calculator)로 무효·적자 없는 안전 투찰가를 1원 단위까지 계산해보세요. "
    "회원가입 없이 무료입니다."
)


def slug_for(code: str) -> str:
    """주제 코드 → 안정적 slug (멱등 판단 기준)."""
    return f"knowledge-{code.lower()}"


def get_topic(code: str) -> Optional[dict]:
    for t in TOPIC_SEEDS:
        if t["code"] == code:
            return t
    return None


def list_topics(db) -> list[dict]:
    """주제 큐 + 초안 존재 여부 (어드민 화면용)."""
    slugs = {slug_for(t["code"]) for t in TOPIC_SEEDS}
    existing = {
        p.slug: p.id
        for p in db.query(models.BlogPost).filter(models.BlogPost.slug.in_(slugs)).all()
    }
    out = []
    for t in TOPIC_SEEDS:
        slug = slug_for(t["code"])
        out.append({
            **t, "track": "knowledge", "slug": slug,
            "draft_exists": slug in existing,
            "post_id": existing.get(slug),
        })
    return out


# ─── LLM 블록 생성 ─────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "너는 한국 공공입찰(나라장터) 도메인 콘텐츠 에디터다. BidEasy 블로그의 구조화 정본을 만든다.\n"
    "브랜드 원칙(위반 금지):\n"
    "- 낙찰가 예측·적중률을 약속하거나 암시하지 않는다. '낙찰률'이라는 표현을 쓰지 않는다.\n"
    "- 통계·숫자·사례 수치를 지어내지 않는다. 구체 숫자가 필요한 자리는 일반 원리로 서술한다.\n"
    "- 톤은 해요체, 친근하고 실무적으로. 과장·공포 조장 금지.\n"
    "- 법·제도 서술은 보수적으로: 단정 대신 '공고문 확인'을 안내한다.\n"
    "JSON 으로만 응답한다:\n"
    '{"hook": "1~2문장 호기심 훅", "summary_30s": "2~3문장 30초 요약", '
    '"key_points": [{"heading": "소제목", "body": "2~4문장"}] (3~5개), '
    '"seo_summary": "검색결과용 1문장 메타 요약", '
    '"image_prompts": [{"slot": "hero"|"diagram", "caption": "한글 캡션(figcaption/alt용)", '
    '"prompt": "영어 이미지 생성 프롬프트"}] (hero 1개 + diagram 1개)}\n'
    "image_prompts 규칙(힉스필드 생성용, CONTENT_ENGINE §5.1):\n"
    "- hero: 텍스트 미포함 개념·은유 이미지. deep blue #3182F6 브랜드 톤, flat vector, no text.\n"
    "- diagram: 본문 핵심 하나를 도식화. 렌더할 한글 라벨을 프롬프트 안에 따옴표로 정확히 명시"
    '("Render the Korean text labels EXACTLY: ..."). 라벨 속 숫자·통계도 지어내지 말 것.\n'
    "- 공통: brand colors #3182F6/#F2F4F6/#191F28/#34C759, flat vector, rounded 20px cards, "
    "no photorealism, no watermark, Korean fintech (Toss) aesthetic. "
    '반드시 "Render ONLY these Korean text labels ... and NO other text anywhere '
    '(no title, no header, no watermark)" 를 포함할 것 — 맥락 설명이 제목 텍스트로 '
    "왜곡 렌더되는 사고 방지(2026-07-19 실측)."
)


def generate_blocks(topic: dict) -> Optional[dict]:
    """주제 → 구조화 정본 블록. 키 미설정/실패 시 None (지어낸 폴백 초안 금지)."""
    if not settings.OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        user_prompt = (
            f"주제: {topic['title']}\n앵글: {topic['angle']}\n"
            f"SEO 타겟 검색어: {topic.get('keyword') or '(없음)'}\n"
            "위 주제로 구조화 정본 블록을 만들어라."
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=1200,
        )
        data = json.loads(resp.choices[0].message.content)
        if not data.get("hook") or not data.get("key_points"):
            return None
        return {
            "track": "knowledge",
            "topic_code": topic["code"],
            "title": topic["title"],
            "target_keyword": topic.get("keyword") or "",
            "hook": data["hook"],
            "summary_30s": data.get("summary_30s", ""),
            "key_points": data["key_points"][:5],
            "data_blocks": [],            # K 트랙 기본 생성은 비움 — 숫자 지어내기 금지
            "internal_links": _DEFAULT_LINKS,
            "cta": _DEFAULT_CTA,
            "seo_summary": data.get("seo_summary", ""),
            # 시각물 반자동(§5.1): 프롬프트만 생성 — 이미지 생성·검수·배치는 사람/세션이 수행
            "image_prompts": (data.get("image_prompts") or [])[:3],
        }
    except Exception:
        logger.exception("content engine LLM block generation failed: %s", topic.get("code"))
        return None


# ─── 블록 → body_md 결정적 렌더 ────────────────────────────────

def _image_placeholder(slot: str, caption: str, slug: str, idx: int) -> str:
    """이미지 자리 — 주석 처리로 직조. 파일 배치·눈검수 후 주석을 해제해야 노출된다.

    (§5.1 반자동 원칙: 파일이 없는 채 발행돼 깨진 이미지가 나가는 사고 방지)
    """
    fname = "hero.png" if slot == "hero" else f"fig{idx}.png"
    return (
        f"<!-- 이미지 자리({slot}): 힉스필드 생성 → /assets/blog/{slug}/{fname} 배치 "
        f"→ 눈검수 후 아래 주석 해제\n![{caption}](/assets/blog/{slug}/{fname})\n-->"
    )


def render_blocks_to_md(blocks: dict, slug: str = "") -> str:
    """구조화 블록 → 마크다운 본문 (결정적 — 같은 블록이면 같은 본문)."""
    prompts = blocks.get("image_prompts") or []
    heroes = [p for p in prompts if p.get("slot") == "hero"]
    diagrams = [p for p in prompts if p.get("slot") == "diagram"]

    L: list[str] = [blocks.get("hook", ""), ""]
    if slug and heroes:
        L += [_image_placeholder("hero", heroes[0].get("caption", ""), slug, 0), ""]
    if blocks.get("summary_30s"):
        L += [f"> **30초 요약** — {blocks['summary_30s']}", ""]
    for i, kp in enumerate(blocks.get("key_points", [])):
        L += [f"## {kp.get('heading', '')}", "", kp.get("body", ""), ""]
        if slug and i == 0 and diagrams:  # 첫 핵심 뒤에 도식 자리
            L += [_image_placeholder("diagram", diagrams[0].get("caption", ""), slug, 1), ""]
    for db_block in blocks.get("data_blocks", []):
        if db_block.get("caption"):
            L += [f"**{db_block['caption']}**", ""]
        for row in db_block.get("table", []):
            L.append(row)
        L.append("")
    L += ["---", "", blocks.get("cta", _DEFAULT_CTA)]
    return "\n".join(L)


# ─── 초안 생성 (검수 게이트: publish_at 없음) ──────────────────

def create_draft_from_topic(db, code: str):
    """주제 코드 → 구조화 정본 초안 저장. 반환 (post|None, status).

    status: created | exists | unknown_topic | llm_unavailable
    멱등 — 같은 주제 slug 초안이 있으면 재생성 안 함.
    """
    topic = get_topic(code)
    if topic is None:
        return None, "unknown_topic"

    slug = slug_for(code)
    existing = db.query(models.BlogPost).filter(models.BlogPost.slug == slug).first()
    if existing is not None:
        return existing, "exists"

    blocks = generate_blocks(topic)
    if blocks is None:
        return None, "llm_unavailable"

    body_md = render_blocks_to_md(blocks, slug=slug)
    html, rt = blog_svc.render(body_md)
    post = models.BlogPost(
        slug=slug,
        title=topic["title"],
        summary=blocks.get("seo_summary") or blocks.get("summary_30s", ""),
        category="입찰상식",
        tags=f"입찰상식, {topic.get('keyword', '')}".strip(", "),
        body_md=body_md,
        body_html=html,
        reading_time=rt,
        status="draft",
        source="auto",
        date="",
        publish_at=None,   # 검수 게이트 — 사람이 승인/예약해야 발행 (CONTENT_ENGINE §5)
        blocks_json=blocks,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post, "created"
