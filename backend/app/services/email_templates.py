"""이메일 본문 템플릿 — 문구·법정 표기의 단일 소스.

정보통신망법이 광고성 메일에 요구하는 것(제목 "(광고)" 표기, 전송자 명칭·연락처,
쉬운 수신거부 방법)은 **개별 템플릿이 기억할 일이 아니다.** 여기 공통 조립기가 강제하고,
템플릿은 알맹이(제목·본문)만 쓴다. 새 템플릿을 추가하는 사람이 법정 표기를 빠뜨릴 수
없도록 만드는 것이 이 모듈의 존재 이유다.

톤: CLAUDE.md §11 — 해요체·친근("사장님, ~"). 낙찰률·예측 표현은 전역 금지.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Callable, Optional

from app.core.config import settings

# 발신자 법정 표기 — 광고·거래 메일 모두 하단에 노출한다.
SENDER_NAME = "BidEasy (호시컴퍼니)"
SENDER_CONTACT = "support@bideasy.kr"

AD_PREFIX = "(광고)"


@dataclass
class RenderedEmail:
    subject: str
    text: str
    html: str


class UnknownTemplate(KeyError):
    """등록되지 않은 템플릿 이름."""


_REGISTRY: dict[str, tuple[str, Callable[[dict], tuple[str, str, str]]]] = {}


def register(name: str, category: str):
    """템플릿 등록 데코레이터. category = marketing | transactional."""
    def _wrap(fn: Callable[[dict], tuple[str, str, str]]):
        _REGISTRY[name] = (category, fn)
        return fn
    return _wrap


def category_of(name: str) -> str:
    if name not in _REGISTRY:
        raise UnknownTemplate(name)
    return _REGISTRY[name][0]


def _btn(href: str, label: str) -> str:
    return (
        f'<a href="{escape(href)}" style="display:inline-block;padding:12px 20px;'
        f'background:#3182F6;color:#fff;border-radius:10px;font-weight:700;'
        f'text-decoration:none;font-size:15px;">{escape(label)}</a>'
    )


def _footer(*, unsubscribe_url: Optional[str], is_ad: bool) -> tuple[str, str]:
    """법정 표기 + 수신거부 안내(광고인 경우 필수)."""
    lines = [f"{SENDER_NAME} · 문의 {SENDER_CONTACT}"]
    if is_ad and unsubscribe_url:
        lines.append(f"광고성 정보 수신을 원치 않으시면 여기서 해지하실 수 있어요: {unsubscribe_url}")
    elif is_ad:
        lines.append(f"수신거부: {SENDER_CONTACT} 로 알려주시면 즉시 처리해 드려요.")
    text = "\n".join(["", "—" * 12, *lines])

    html_parts = [
        '<hr style="border:none;border-top:1px solid #E5E8EB;margin:28px 0 14px;">',
        f'<p style="font-size:12px;color:#8B95A1;line-height:1.6;margin:0;">'
        f"{escape(SENDER_NAME)} · 문의 "
        f'<a href="mailto:{SENDER_CONTACT}" style="color:#8B95A1;">{SENDER_CONTACT}</a></p>',
    ]
    if is_ad and unsubscribe_url:
        html_parts.append(
            f'<p style="font-size:12px;color:#8B95A1;line-height:1.6;margin:6px 0 0;">'
            f'광고성 정보 수신을 원치 않으시면 '
            f'<a href="{escape(unsubscribe_url)}" style="color:#8B95A1;text-decoration:underline;">'
            f"수신거부</a>하실 수 있어요.</p>"
        )
    return text, "".join(html_parts)


def _wrap_html(body: str, footer_html: str) -> str:
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Pretendard,sans-serif;'
        'max-width:560px;margin:0 auto;padding:28px 22px;color:#191F28;">'
        f"{body}{footer_html}</div>"
    )


def render(name: str, ctx: Optional[dict] = None, *, unsubscribe_url: Optional[str] = None) -> RenderedEmail:
    """템플릿 렌더 + 법정 표기 부착. 광고 카테고리면 제목에 "(광고)" 를 강제한다."""
    if name not in _REGISTRY:
        raise UnknownTemplate(name)
    category, fn = _REGISTRY[name]
    subject, text_body, html_body = fn(ctx or {})

    is_ad = category == "marketing"
    if is_ad and not subject.startswith(AD_PREFIX):
        subject = f"{AD_PREFIX} {subject}"

    footer_text, footer_html = _footer(unsubscribe_url=unsubscribe_url, is_ad=is_ad)
    return RenderedEmail(
        subject=subject[:200],
        text=text_body + footer_text,
        html=_wrap_html(html_body, footer_html),
    )


# ─────────────────────────── 템플릿 ───────────────────────────
@register("lead_welcome", "marketing")
def _lead_welcome(ctx: dict) -> tuple[str, str, str]:
    """무료 자격 진단 직후 웰컴 — 진단 결과를 다시 손에 쥐어준다."""
    region = ctx.get("region") or ""
    industry = ctx.get("industry") or "우리 회사"
    matched = int(ctx.get("matched_count") or 0)
    web = settings.PUBLIC_WEB_URL

    subject = f"{region} {industry}, 지금 넣을 수 있는 공고 {matched}건 정리해 드렸어요".strip()
    text = (
        f"사장님, 진단 결과 {region} {industry} 기준으로 자격이 맞는 공고가 {matched}건이었어요.\n\n"
        "새 공고는 매일 올라오니, 조건에 맞는 건이 뜨면 이어서 알려드릴게요.\n"
        f"지금 목록 다시 보기: {web}/diagnose\n"
        f"나라장터 화면 위에서 바로 확인하려면: {web}/guide\n"
    )
    html = (
        f'<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님, 진단 결과 '
        f'<b>{escape(region)} {escape(industry)}</b> 기준으로 자격이 맞는 공고가 '
        f'<b style="color:#3182F6;">{matched}건</b>이었어요.</p>'
        '<p style="font-size:15px;line-height:1.7;color:#4E5968;margin:0 0 20px;">'
        "새 공고는 매일 올라옵니다. 조건에 맞는 건이 뜨면 이어서 알려드릴게요.</p>"
        f"{_btn(f'{web}/diagnose', '내 조건 공고 다시 보기')}"
    )
    return subject, text, html


@register("trial_expiry", "transactional")
def _trial_expiry(ctx: dict) -> tuple[str, str, str]:
    """체험 만료 안내 — 거래 관련 고지라 광고 동의와 무관하게 발송한다."""
    days_left = int(ctx.get("days_left") or 0)
    web = settings.PUBLIC_WEB_URL

    subject = f"Pro 체험이 {days_left}일 뒤 끝나요" if days_left > 0 else "Pro 체험이 오늘 끝나요"
    text = (
        f"사장님, 사용 중이신 Pro 체험이 {days_left}일 뒤 종료돼요.\n"
        "종료되면 자격 판정·안전 투찰 계산은 Free 한도로 돌아갑니다.\n"
        f"이어서 쓰시려면: {web}/pricing\n"
    )
    html = (
        f'<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님, 사용 중이신 '
        f'<b>Pro 체험</b>이 <b style="color:#3182F6;">{days_left}일</b> 뒤 종료돼요.</p>'
        '<p style="font-size:15px;line-height:1.7;color:#4E5968;margin:0 0 20px;">'
        "종료되면 자격 판정·안전 투찰 계산이 Free 한도로 돌아갑니다.</p>"
        f"{_btn(f'{web}/pricing', '이어서 사용하기')}"
    )
    return subject, text, html
