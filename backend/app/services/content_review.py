"""자동 검수 게이트 (콘텐츠 엔진 Phase 1 — 그림자 모드).

왜 필요한가: 지금 발행 품질을 지키는 유일한 장치가 **사람의 눈**이다. 그래서 사람이
멈추면 블로그가 멈춘다(주제 24개 중 1편만 발행된 이유). 자동화의 답은 게이트를
없애는 게 아니라 **기계가 볼 수 있는 것은 기계가 보고, 사람은 예외만** 처리하게 만드는 것.

이 모듈은 초안을 검사해 판정을 남긴다:
    PASS  — 결정적 규칙·심판 모두 통과
    WARN  — 사람이 한 번 봐두면 좋은 신호 (자동 발행 후보이되 유예)
    FAIL  — 브랜드·정책 위반 가능성 (사람 필수)

**기본 그림자 모드**: 이 모듈은 판정을 저장할 뿐 발행 API를 직접 막지 않는다.
다만 검증 표본을 쌓은 K-트랙의 주간 태스크는 Phase 2 소비자로서 완결된 PASS/WARN만
유예 예약하고, FAIL·검사 생략은 사람에게 보낸다. 다른 트랙은 계속 그림자 모드다.

검사 종류:
  결정적(LLM 불필요·100% 재현) — 금칙어 / 출처 없는 수치 / 중복도 / 구조 / 이미지 참조
  LLM 심판(반박 관점)          — 사실 오류·법령 단정·과장. 생성과 다른 프롬프트를 쓴다.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.db import models
from app.services import llm_gateway

logger = logging.getLogger(__name__)

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
REVIEW_LEVEL_ORDER = {PASS: 0, WARN: 1, FAIL: 2}

# K-트랙 자동발행이 "검수 완료"로 인정하려면 모두 있어야 하는 검사 집합.
# 소비자가 자체 목록을 복사하면 새 검사 추가 시 라우터가 조용히 옛 판정을 통과시키므로
# 검수 모듈을 단일 소스로 둔다.
AUTO_PUBLISH_REQUIRED_CHECK_CODES = frozenset({
    "banned_terms",
    "unsourced_numbers",
    "duplication",
    "structure",
    "image_refs",
    "llm_judge",
})


# ─── ① 금칙어 ─────────────────────────────────────────────────
# 전역 규칙: '낙찰률' 금지 + 비예측 포지션. 마케팅뿐 아니라 본문에서도 금지.
_BANNED = [
    ("낙찰률", "전역 금지어 — 승률 지표는 과적합이고 사정률 추첨은 랜덤"),
    ("적중률", "예측 정확도 암시 — 비예측 포지션 위반"),
    ("예측 정확도", "예측 정확도 암시 — 비예측 포지션 위반"),
    ("낙찰 보장", "보장 표현 금지"),
    ("낙찰가 예측", "우리가 하지 않는다고 공개 선언한 기능"),
]
# "'낙찰가 예측' 광고를 믿으면 안 되는 이유"처럼 **비판 맥락**은 정당하다.
# 부정·인용 신호가 같은 문장에 있으면 위반으로 보지 않는다.
_CRITIQUE_HINTS = ("믿으면", "안 되", "못 한", "않습니다", "않아요", "하지 않", "불가능",
                   "환상", "주의", "조심", "허위", "과장", "광고", "'", '"', "‘", "“")


# 문장 분리 — **숫자 사이의 마침표는 자르지 않는다**. 안 그러면 "89.745%" 가
# "89" / "745%" 로 쪼개져 하한율이 통째로 '출처 없는 수치'로 잡힌다(실측으로 발견).
_SENT_SPLIT = re.compile(r"(?<!\d)[.!?]+(?!\d)|\n+")


def _sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text) if s and s.strip()]


def check_banned_terms(text: str) -> dict:
    hits = []
    for sent in _sentences(text):
        for term, why in _BANNED:
            if term in sent and not any(h in sent for h in _CRITIQUE_HINTS):
                hits.append({"term": term, "why": why, "quote": sent.strip()[:120]})
    return {
        "code": "banned_terms",
        "level": FAIL if hits else PASS,
        "hits": hits,
        "detail": f"금칙어 {len(hits)}건" if hits else "금칙어 없음",
    }


# ─── ② 출처 없는 수치 ─────────────────────────────────────────
# 통계처럼 읽히는 숫자가 팩트시트·DB 숫자에 없으면 환각 가능성.
# 정밀도가 아직 미검증이라 WARN(자문) 수준으로 둔다 — 그림자 모드로 노이즈를 측정한 뒤 조정.
def _lower_limit_numbers() -> set:
    """낙찰하한율 화이트리스트 — `lower_limits.py`(단일 소스)에서 끌어온다.

    하드코딩하면 요율 개정 때마다 게이트가 정상 글을 오탐한다(실측: 87.745·86.745 가
    전부 '출처 없는 수치'로 잡혔음). 단일 소스를 따라가게 해서 드리프트를 없앤다.
    """
    from app.services import lower_limits as ll
    vals = {r for _, r in ll._CONSTRUCTION_2026} | {r for _, r in ll._CONSTRUCTION_OLD}
    vals |= set(ll.LEGACY_RATES.values())
    out = set()
    for v in vals:
        out.add(f"{v:g}")                     # 87.495
        if float(v).is_integer():
            out.add(str(int(v)))              # 60
    return out


_FACTSHEET_NUMBERS = {
    "15", "4", "2", "3", "10",       # 복수예가 15→4개·변동폭 ±2/3%·금액구간 10억
} | _lower_limit_numbers()
_STAT_PATTERNS = [
    r"(\d+(?:\.\d+)?)\s*%",
    r"(\d+(?:,\d{3})*)\s*개사",
    r"(\d+(?:,\d{3})*)\s*건",
    r"(\d+(?:\.\d+)?)\s*배",
]
# 서술형 표현 안의 숫자는 통계 주장이 아니다 (예: "3분 안에", "5가지", "1원 차이")
_BENIGN_CONTEXT = re.compile(r"\d+\s*(?:분|초|시간|일|주|개월|년|가지|선|단계|위|원 차이|번째)")
# 가정·예시로 명시된 숫자는 사실 주장이 아니다 — "투찰률(예: 92%)", "~라고 해볼게요".
# (실측: K5 초안에서 예시 투찰률이 전부 '출처 없는 수치'로 잡혔음)
_HYPOTHETICAL = ("예:", "예를 들어", "예시", "가정", "해볼게요", "해볼까요", "쳐볼게요", "라고 치면")


def check_unsourced_numbers(text: str, allowed: Optional[set] = None) -> dict:
    allowed = (allowed or set()) | _FACTSHEET_NUMBERS
    found = []
    for sent in _sentences(text):
        if _BENIGN_CONTEXT.search(sent) or any(h in sent for h in _HYPOTHETICAL):
            continue
        for pat in _STAT_PATTERNS:
            for m in re.finditer(pat, sent):
                raw = m.group(1).replace(",", "")
                if raw not in allowed:
                    found.append({"value": m.group(0).strip(), "quote": sent.strip()[:120]})
    return {
        "code": "unsourced_numbers",
        "level": WARN if found else PASS,
        "hits": found[:10],
        "detail": (
            f"팩트시트·DB 에 없는 수치 {len(found)}건 — 환각 가능성(확인 필요)"
            if found else "출처 없는 수치 없음"
        ),
    }


def allowed_numbers_from_blocks(blocks: dict) -> set:
    """data_blocks(DB 결정적 숫자)에 등장하는 값은 출처 있는 수치로 인정."""
    out: set = set()
    for b in (blocks or {}).get("data_blocks") or []:
        for row in (b.get("numbers") or []):
            for v in (row.values() if isinstance(row, dict) else []):
                if isinstance(v, (int, float)):
                    out.add(str(int(v)) if float(v).is_integer() else str(v))
        for row in (b.get("table") or []):
            out.update(re.findall(r"\d+(?:\.\d+)?", str(row)))
    return out


# ─── ③ 중복도 (§9.2 doorway/중복 방어) ────────────────────────

def _trigrams(text: str) -> set:
    t = re.sub(r"\s+", "", re.sub(r"[^\w가-힣]", "", text))
    return {t[i:i + 3] for i in range(len(t) - 2)} if len(t) >= 3 else set()


def _similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def check_duplication(db, body_md: str, exclude_slug: str = "") -> dict:
    """기존 발행글과의 유사도. 주간 데이터스토리가 서로 닮아가는 것을 잡는 게 목적."""
    worst, worst_slug = 0.0, ""
    q = db.query(models.BlogPost).filter(models.BlogPost.status == "published")
    if exclude_slug:
        q = q.filter(models.BlogPost.slug != exclude_slug)
    for other in q.limit(200).all():
        s = _similarity(body_md, other.body_md or "")
        if s > worst:
            worst, worst_slug = s, other.slug
    level = FAIL if worst >= 0.75 else (WARN if worst >= 0.55 else PASS)
    return {
        "code": "duplication",
        "level": level,
        "max_similarity": round(worst, 3),
        "nearest": worst_slug,
        "detail": (
            f"기존 글 '{worst_slug}' 와 유사도 {worst:.0%}" if worst_slug else "비교 대상 없음"
        ),
    }


# ─── ④ 구조 ───────────────────────────────────────────────────

MIN_BODY_CHARS = 2000


def check_structure(body_md: str, blocks: Optional[dict] = None, enforce_length: bool = True) -> dict:
    """구조 검사.

    `enforce_length`: 분량 기준은 **LLM 이 쓴 글에만** 적용한다. 얕은 자동 생성물을
    막으려고 만든 규칙이라, 사람이 길이를 정한 손글씨(상록수)에까지 들이대면
    정상 글이 전부 WARN 이 된다(실측: 발행된 4편 모두 1,052~1,459자로 걸렸음).
    """
    issues = []
    plain = re.sub(r"<!--.*?-->", "", body_md, flags=re.S)   # 주석 이미지 자리 제외
    chars = len(re.sub(r"\s+", "", plain))
    if enforce_length and chars < MIN_BODY_CHARS:
        issues.append(f"본문 {chars}자 — 기준 {MIN_BODY_CHARS}자 미만")
    headings = len(re.findall(r"^##\s+", body_md, re.M))
    if headings < 3:
        issues.append(f"섹션 {headings}개 — 너무 얕음")
    if not re.search(r"\]\(/(?:calculator|diagnose|search|blog)", body_md):
        issues.append("내부링크 없음 — 회수 경로 누락")
    return {
        "code": "structure",
        "level": WARN if issues else PASS,
        "issues": issues,
        "chars": chars,
        "headings": headings,
        "detail": "; ".join(issues) if issues else "구조 정상",
    }


# ─── ⑤ 이미지 참조 무결성 ─────────────────────────────────────

def check_image_refs(body_md: str, slug: str) -> dict:
    """노출된(주석 해제된) 이미지가 이 글의 자산 경로를 가리키는지.

    파일 존재 여부는 백엔드에서 확인할 수 없다(정적 자산은 nginx 소유). 대신 **경로 규약
    위반**을 잡는다 — 다른 글의 slug 를 가리키거나 placeholder 가 선언한 파일명과
    어긋나는 경우(리뷰에서 확인된 fig0/fig1 불일치가 여기에 걸린다).
    """
    commented = set(re.findall(r"<!--.*?\]\((/assets/blog/[^)]+)\).*?-->", body_md, re.S))
    live = set(re.findall(r"\]\((/assets/blog/[^)]+)\)", body_md)) - commented
    issues = []
    for path in live:
        if slug and f"/assets/blog/{slug}/" not in path:
            issues.append(f"다른 글 자산 참조: {path}")
    return {
        "code": "image_refs",
        "level": WARN if issues else PASS,
        "live": sorted(live),
        "issues": issues,
        "detail": "; ".join(issues) if issues else f"노출 이미지 {len(live)}개 — 경로 정상",
    }


# ─── ⑥ LLM 심판 (반박 관점) ───────────────────────────────────

_JUDGE_PROMPT = (
    "너는 한국 공공입찰 도메인의 **깐깐한 팩트체커**다. 아래 블로그 초안에서 문제를 "
    "찾는 것이 임무다. 칭찬하지 말고, 문제만 지적하라. 문제가 없으면 빈 배열을 반환하라.\n"
    "중대도 기준:\n"
    "- high: 사실과 다른 법·제도 서술, 확인 불가한 통계·수치, 낙찰가 예측/적중률 약속, "
    "실존 업체·사람을 특정한 사례, 단정적 법률 조언\n"
    "- medium: 과장·공포 조장, 근거 없는 일반화, 공고문 확인 안내가 필요한데 단정한 부분\n"
    "- low: 어색한 표현, 반복\n"
    "주의: 이 브랜드는 '낙찰가를 예측하지 않는다'는 포지션이다. 예측을 비판하는 서술은 "
    "정상이니 문제로 잡지 마라.\n"
    'JSON 으로만 응답: {"issues": [{"severity": "high|medium|low", "quote": "문제 문장 일부", '
    '"why": "왜 문제인지 한 문장"}]}'
)


def check_llm_judge(title: str, body_md: str) -> dict:
    if not llm_gateway.available():
        return {"code": "llm_judge", "level": PASS, "skipped": True,
                "detail": "LLM 키 미설정 — 심판 건너뜀"}
    try:
        data = llm_gateway.chat_json(
            _JUDGE_PROMPT,
            f"제목: {title}\n\n본문:\n{body_md[:12000]}",
            max_tokens=1500,
            temperature=0.0,          # 심판은 일관성 우선
            model=llm_gateway.cheap_model(),
        )
        issues = [i for i in (data.get("issues") or []) if i.get("quote")]
        highs = [i for i in issues if i.get("severity") == "high"]
        meds = [i for i in issues if i.get("severity") == "medium"]
        level = FAIL if highs else (WARN if meds else PASS)
        return {
            "code": "llm_judge",
            "level": level,
            "issues": issues[:10],
            "detail": f"high {len(highs)} / medium {len(meds)} / low {len(issues) - len(highs) - len(meds)}",
        }
    except Exception:
        logger.exception("content review LLM judge failed")
        # 심판 실패가 초안을 막지는 않는다. 다만 '검사 못 함'을 숨기지 않는다.
        return {"code": "llm_judge", "level": WARN, "skipped": True,
                "detail": "심판 호출 실패 — 사람이 확인 필요"}


# ─── 통합 ─────────────────────────────────────────────────────

def review_post(db, post, use_llm: bool = True) -> dict:
    """BlogPost 초안 검수 → 판정 dict (이 함수는 저장만, 라우팅은 소비자가 결정)."""
    title = post.title or ""
    summary = getattr(post, "summary", "") or ""
    body = post.body_md or ""
    blocks = getattr(post, "blocks_json", None) or {}
    # 제목·요약도 검색결과/목록/공유 미리보기에 공개되는 콘텐츠다. 본문만 검사하면
    # 금칙어나 근거 없는 수치가 메타 텍스트로 우회할 수 있으므로 결정적 검사에 포함한다.
    public_text = "\n\n".join(part for part in (title, summary, body) if part)
    checks = [
        check_banned_terms(public_text),
        check_unsourced_numbers(public_text, allowed_numbers_from_blocks(blocks)),
        check_duplication(db, body, exclude_slug=post.slug or ""),
        # 분량 기준은 자동 생성물에만 (손글씨 상록수는 사람이 길이를 정한 것)
        check_structure(body, blocks, enforce_length=(getattr(post, "source", "") == "auto")),
        check_image_refs(body, post.slug or ""),
    ]
    if use_llm:
        checks.append(check_llm_judge(title, f"요약: {summary}\n\n{body}"))

    verdict = max((c["level"] for c in checks), key=lambda lv: REVIEW_LEVEL_ORDER[lv])
    return {
        "verdict": verdict,
        "checks": checks,
        "blocking": [c["code"] for c in checks if c["level"] == FAIL],
        "advisory": [c["code"] for c in checks if c["level"] == WARN],
        "mode": "shadow",   # 판정 생성 모드. K-트랙 소비자가 별도 Phase 2 라우팅에 사용.
    }


def review_and_store(db, post, use_llm: bool = True) -> Optional[dict]:
    """검수 실행 + `review_json` 저장. best-effort — 실패해도 초안 생성을 막지 않는다."""
    try:
        result = review_post(db, post, use_llm=use_llm)
        post.review_json = result
        db.commit()
        db.refresh(post)
        return result
    except Exception:
        logger.exception("review_and_store failed for post %s", getattr(post, "id", "?"))
        try:
            db.rollback()
        except Exception:
            pass
        return None
