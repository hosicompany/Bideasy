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

# 검증된 제도 팩트 시트 — "숫자 지어내기 금지" 가드에서 제외되는 법정·제도 사실.
# (2026-07-19 품질 개편: 이 시트가 없으면 LLM 이 제도 수치까지 회피해 내용이 얕아짐)
_DOMAIN_FACTS = (
    "[검증된 제도 팩트 — 이 수치는 정확히 사용 가능]\n"
    "- 예정가격 결정: 발주기관이 기초금액 기준 복수예비가격 15개 작성 → 입찰참가자 추첨으로 4개 선택 → 그 산술평균이 예정가격. 개찰 전까지 비공개, 누구도 미리 알 수 없음.\n"
    "- 예비가격 변동폭: 통상 국가기관 ±2%, 지방자치단체 ±3% (기관·공고별 상이 — 공고문 확인).\n"
    "- 낙찰하한선 = 예정가격 × 낙찰하한율. 이 미만 투찰은 무효(자동 탈락). 공사 하한율은 금액 구간별 상이(2026-01-30 시행 기준 87.495~89.745%, 예: 추정가격 10억 미만 공사 89.745%).\n"
    "- 적격심사: 낙찰하한선 위 최저가 순으로 심사. 실적·경영상태·신인도 등 점수 통과 필요.\n"
    "- A값: 국민연금·건강보험·산재·고용·노인장기요양 보험료 합계. 사후정산 비목이라 투찰률이 적용되지 않음 → 분리 계산하지 않으면 견적 왜곡.\n"
    "- 지역제한 입찰: 공고 지역에 주된 영업소(본사)가 있어야 참여 가능. 공동수급(컨소시엄) 허용 여부는 공고별 상이.\n"
    "- 소액수의견적: 소액 공사 등에서 2인 이상 견적 제출로 계약상대자 결정. 사정률 추첨 구조는 동일하게 랜덤.\n"
    "- 입찰무효 흔한 사유: 하한선 미만 투찰, 마감시각 경과, 인증서 문제, 필수서류 누락, 참가자격 미달.\n"
    "[금지] 위 시트에 없는 통계·승률·사례 수치·업체명은 절대 지어내지 말 것. 필요하면 수치 없이 원리로 서술."
)

_SYSTEM_PROMPT = (
    "너는 한국 공공입찰(나라장터) 도메인의 전문 콘텐츠 에디터다. BidEasy 블로그의 구조화 정본을 만든다.\n"
    "브랜드 원칙(위반 금지):\n"
    "- 낙찰가 예측·적중률을 약속하거나 암시하지 않는다. '낙찰률'이라는 표현을 쓰지 않는다.\n"
    "- 톤은 해요체, 친근하고 실무적으로. 과장·공포 조장 금지. 법·제도 단정 대신 '공고문 확인' 안내.\n"
    + _DOMAIN_FACTS + "\n"
    "품질 기준(중요 — 얕은 글 금지):\n"
    "- 본문 섹션 합계 2,800자 이상(읽는 시간 5분+). 섹션마다 반드시 새로운 정보 — 같은 말 반복 금지.\n"
    "- 각 섹션 body 는 400~700자 마크다운(불릿·**굵게** 활용 가능). 제도 메커니즘을 팩트 시트 수치로 구체적으로 설명.\n"
    "- 초보 사장님이 '오늘 바로 써먹을' 실무 디테일 포함(무엇을 확인하고, 무엇을 조심하는지).\n"
    "- 깊이: 각 섹션은 '무엇을'에서 멈추지 말고 '왜 그런지'(제도적 이유·설계 의도)까지 설명하고, "
    "수치 없는 서사형 실수 시나리오(예: '하한선을 옛 기준으로 계산한 사장님이…')를 1개 이상 녹일 것.\n"
    "- 몰입(독자가 '내 이야기'로 느끼게): 글 전체를 관통하는 가상의 페르소나 1명을 세워라 — "
    "소규모 전문건설(전기공사 등) 1~10인 업체 사장님, 견적·투찰·현장을 혼자 다 챙기는 사람. "
    "hook 은 그 사장님의 구체적 장면(예: 마감 40분 전 사무실, 공고문을 세 번째 다시 읽는 밤)으로 열고, "
    "본문 섹션 중 2~3곳에서 같은 인물의 상황으로 개념을 이어서 설명해 스토리라인을 만들 것. "
    "단, 가상 예시임이 자연스럽게 드러나는 서술('~라고 해볼게요', '흔한 장면이에요')을 쓰고, "
    "실존 업체명·실명·구체적 낙찰 실적 수치는 절대 만들지 말 것(가짜 후기 금지 — 상황 기반 공감만).\n"
    "JSON 으로만 응답한다:\n"
    '{"hook": "1~2문장 호기심 훅", "summary_30s": "2~3문장 30초 요약", '
    '"sections": [{"heading": "소제목", "body": "400~700자 마크다운"}] (5~7개), '
    '"checklist": ["실무 체크 문장"] (3~5개), '
    '"faq": [{"q": "질문", "a": "2~3문장 답"}] (2~3개), '
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
    primary_key = settings.CONTENT_LLM_API_KEY or settings.OPENAI_API_KEY
    if not primary_key:
        return None
    try:
        from openai import OpenAI

        # 정본 작성 모델은 OpenAI 호환 엔드포인트(OpenRouter 등)로 교체 가능 —
        # 폴백(gpt-4o-mini)은 항상 OpenAI 직결이라 프로바이더 장애와 독립적이다.
        base_url = settings.CONTENT_LLM_BASE_URL or None
        primary_client = OpenAI(api_key=primary_key, base_url=base_url)
        user_prompt = (
            f"주제: {topic['title']}\n앵글: {topic['angle']}\n"
            f"SEO 타겟 검색어: {topic.get('keyword') or '(없음)'}\n"
            "위 주제로 구조화 정본 블록을 만들어라."
        )
        def _chat(client, model: str, extra: str = "") -> dict:
            kwargs = dict(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt + extra},
                ],
                response_format={"type": "json_object"},
                max_tokens=4000,
            )
            # Claude 계열(Sonnet 5 등)은 temperature 등 샘플링 파라미터를 거부(400)
            if "claude" not in model.lower():
                kwargs["temperature"] = 0.5
            resp = client.chat.completions.create(**kwargs)
            return json.loads(resp.choices[0].message.content)

        def _call(extra: str = "") -> dict:
            # 상위 모델 우선(깊이), 실패(미지원 모델·프로바이더 장애 등) 시 4o-mini 폴백
            primary = getattr(settings, "CONTENT_LLM_MODEL", "gpt-4o-mini")
            try:
                return _chat(primary_client, primary, extra)
            except Exception:
                if not settings.OPENAI_API_KEY:
                    raise  # 폴백 경로(OpenAI 직결) 불가 — 정직하게 실패
                logger.warning("content model %s failed — fallback to gpt-4o-mini", primary)
                fallback_client = OpenAI(api_key=settings.OPENAI_API_KEY)
                return _chat(fallback_client, "gpt-4o-mini", extra)

        data = _call()
        sections = data.get("sections") or data.get("key_points") or []
        total_chars = sum(len(s.get("body", "")) for s in sections)
        if total_chars < 2000:
            # 분량 미달 1회 재시도 — 5분 이상 읽을거리(≈2,800자+)가 품질 기준
            data = _call(
                f"\n\n[재시도] 방금 생성분은 본문 {total_chars}자로 분량 미달이었다. "
                "섹션 6~7개, 각 500~700자로 훨씬 깊고 길게 다시 써라. 반복 금지."
            )
            sections = data.get("sections") or data.get("key_points") or []
        if not data.get("hook") or not sections:
            return None
        return {
            "track": "knowledge",
            "topic_code": topic["code"],
            "title": topic["title"],
            "target_keyword": topic.get("keyword") or "",
            "hook": data["hook"],
            "summary_30s": data.get("summary_30s", ""),
            "key_points": sections[:7],
            "checklist": (data.get("checklist") or [])[:5],
            "faq": (data.get("faq") or [])[:3],
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
    if blocks.get("checklist"):
        L += ["## ✅ 오늘 바로 쓰는 체크리스트", ""]
        L += [f"- {item}" for item in blocks["checklist"]] + [""]
    if blocks.get("faq"):
        L += ["## 자주 묻는 질문", ""]
        for f in blocks["faq"]:
            L += [f"**Q. {f.get('q', '')}**", "", f.get("a", ""), ""]
    for db_block in blocks.get("data_blocks", []):
        if db_block.get("caption"):
            L += [f"**{db_block['caption']}**", ""]
        for row in db_block.get("table", []):
            L.append(row)
        L.append("")
    L += ["---", "", blocks.get("cta", _DEFAULT_CTA)]
    return "\n".join(L)


# ─── 초안 생성 (검수 게이트: publish_at 없음) ──────────────────

def create_draft_from_topic(db, code: str, force: bool = False):
    """주제 코드 → 구조화 정본 초안 저장. 반환 (post|None, status).

    status: created | exists | unknown_topic | llm_unavailable | published_locked
    멱등 — 같은 주제 slug 초안이 있으면 재생성 안 함.
    force=True 면 기존 draft 를 재생성(덮어쓰기) — 발행본은 보호(published_locked).
    """
    topic = get_topic(code)
    if topic is None:
        return None, "unknown_topic"

    slug = slug_for(code)
    existing = db.query(models.BlogPost).filter(models.BlogPost.slug == slug).first()
    if existing is not None:
        if not force:
            return existing, "exists"
        if existing.status == "published":
            return existing, "published_locked"
        blocks = generate_blocks(topic)
        if blocks is None:
            return None, "llm_unavailable"
        body_md = render_blocks_to_md(blocks, slug=slug)
        html, rt = blog_svc.render(body_md)
        existing.title = topic["title"]
        existing.summary = blocks.get("seo_summary") or blocks.get("summary_30s", "")
        existing.body_md = body_md
        existing.body_html = html
        existing.reading_time = rt
        existing.blocks_json = blocks
        existing.channel_assets_json = None  # 정본이 바뀌었으니 파생 캐시 무효화
        db.commit()
        db.refresh(existing)
        return existing, "created"

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


# ─── Phase 2: 채널 파생 하네스 (blocks → channel_assets_json) ──

_DERIVE_SYSTEM_PROMPT = (
    "너는 BidEasy(한국 공공입찰 SaaS)의 채널 콘텐츠 에디터다. 검수 완료된 블로그 정본 블록을 "
    "받아 채널별 파생 카피를 만든다. 브랜드 원칙: 낙찰가 예측·적중률 약속 금지, '낙찰률' 표현 금지, "
    "숫자·통계 지어내기 금지(블록에 있는 것만 사용), 해요체, 과장 금지.\n"
    "JSON 으로만 응답한다:\n"
    '{"instagram_cards": [카드뉴스 5~6장 — cardmaker 규격: '
    '{"kind": "cover"|"content"|"highlight"|"cta", "badge": "상단 라벨(≤10자)", '
    '"headline": "헤드라인 — 줄당 최대 12자, 최대 2줄, 줄바꿈은 \\n 으로 직접 삽입", '
    '"body": "본문 — 줄당 최대 22자, 최대 4줄, \\n 직접 삽입", '
    '"fl": "bideasy.kr", "fr": "n / N"}] — 1장=cover, 마지막=cta, 중간=content(핵심 1개씩),\n'
    '"reels_script": {"hook_3s": "3초 훅 한 문장", "points": ["핵심 문장"] (2~3개), "cta": "마무리 한 문장"},\n'
    '"youtube": {"script_md": "1~2분 말하기체 대본(마크다운)", "chapters": ["00:00 제목"...], '
    '"description": "설명란(마지막 줄에 bideasy.kr 링크)"},\n'
    '"naver_summary_md": "네이버 블로그용 요약 본문(마크다운, 핵심만 짧게 + 마지막에 원문 안내 문구)"}'
)


def derive_channel_assets(blocks: dict) -> Optional[dict]:
    """정본 블록 → 채널 파생 자산. 키 미설정/실패 시 None (가짜 자산 금지)."""
    if not settings.OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _DERIVE_SYSTEM_PROMPT},
                {"role": "user", "content": "정본 블록:\n" + json.dumps(blocks, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=2500,
        )
        data = json.loads(resp.choices[0].message.content)
        if not data.get("instagram_cards"):
            return None
        # fr 페이지 표기 결정적 보정 (n / N)
        cards = data["instagram_cards"][:6]
        total = len(cards)
        for i, c in enumerate(cards, 1):
            c["fl"] = c.get("fl") or "bideasy.kr"
            c["fr"] = f"{i} / {total}"
        data["instagram_cards"] = cards
        return data
    except Exception:
        logger.exception("channel assets derivation failed")
        return None


def ensure_channel_assets(db, post) -> bool:
    """발행 훅용 — blocks 있고 자산 없으면 파생 생성·저장. 성공 시 True.

    best-effort: 실패해도 예외를 밖으로 던지지 않는다(발행을 막지 않음).
    """
    try:
        if not getattr(post, "blocks_json", None) or getattr(post, "channel_assets_json", None):
            return False
        assets = derive_channel_assets(post.blocks_json)
        if assets is None:
            return False
        post.channel_assets_json = assets
        db.commit()
        return True
    except Exception:
        logger.exception("ensure_channel_assets failed for post %s", getattr(post, "id", "?"))
        try:
            db.rollback()
        except Exception:
            pass
        return False


# 큐 잔여가 이 이하로 떨어지면 관리자에게 보충 경보 (약 1개월 분량)
LOW_QUEUE_WATERMARK = 4


def remaining_topics(db) -> int:
    """아직 초안이 생성되지 않은(미소비) 주제 수."""
    slugs = [slug_for(t["code"]) for t in TOPIC_SEEDS]
    consumed = (
        db.query(models.BlogPost.slug)
        .filter(models.BlogPost.slug.in_(slugs))
        .count()
    )
    return len(TOPIC_SEEDS) - consumed


_PROPOSE_SYSTEM_PROMPT = (
    "너는 BidEasy(한국 공공입찰 안전 비서 SaaS) 블로그의 편집장이다. "
    "'입찰상식' 트랙의 신규 주제 후보를 제안한다.\n"
    "브랜드 원칙(위반 금지): 낙찰가 예측·적중률 소재 금지, '낙찰률' 표현 금지, "
    "안전·자격·정밀·정직 프레임 유지. 소규모 전문건설업(1~10인) 사장님 대상.\n"
    "각 후보는 검색 수요가 있을 법한 실무 주제여야 하고, 기존 주제와 겹치면 안 된다.\n"
    'JSON 으로만 응답: {"candidates": [{"title": "주제(가제)", "angle": "앵글 한 줄", '
    '"keyword": "SEO 타겟 검색어", "priority": "P1|P2|P3"}]}'
)


def propose_topic_candidates(n: int = 8) -> Optional[list]:
    """신규 주제 후보 n개 제안 (자동 편입 아님 — 사람 검토 후 시드 추가).

    키 미설정/실패 시 None. 큐 보충의 편집 결정권은 사람에게 남긴다.
    """
    if not settings.OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        existing = "\n".join(f"- {t['title']} ({t['angle']})" for t in TOPIC_SEEDS)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _PROPOSE_SYSTEM_PROMPT},
                {"role": "user", "content": f"기존 주제 목록(중복 금지):\n{existing}\n\n신규 후보 {n}개를 제안하라."},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=1500,
        )
        data = json.loads(resp.choices[0].message.content)
        cands = [
            c for c in (data.get("candidates") or [])
            if c.get("title") and "낙찰률" not in c["title"] and "낙찰률" not in c.get("angle", "")
        ]
        return cands[:n] or None
    except Exception:
        logger.exception("topic candidate proposal failed")
        return None


def next_unconsumed_topic(db) -> Optional[dict]:
    """주간 루프용 — 아직 초안이 없는 최우선(P1→P2→P3, 코드순) 주제."""
    for t in sorted(TOPIC_SEEDS, key=lambda x: (x["priority"], int(x["code"][1:]))):
        exists = db.query(models.BlogPost).filter(
            models.BlogPost.slug == slug_for(t["code"])
        ).first()
        if exists is None:
            return t
    return None
