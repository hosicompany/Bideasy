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
    # 매칭 상한(MATCH_LIMIT)에 걸린 값이면 실제로는 더 많다 — 진단 화면의 `capped` 와
    # 같은 정직성 장치. 상한값을 딱 떨어지게 말하면 사실과 다른 수를 말하게 된다.
    label = f"{matched}건+" if ctx.get("capped") else f"{matched}건"

    subject = f"{region} {industry}, 지금 넣을 수 있는 공고 {label} 정리해 드렸어요".strip()
    text = (
        f"사장님, 진단 결과 {region} {industry} 기준으로 자격이 맞는 공고가 {label}이었어요.\n\n"
        "새 공고는 매일 올라오니, 조건에 맞는 건이 뜨면 이어서 알려드릴게요.\n"
        f"지금 목록 다시 보기: {web}/diagnose\n"
        f"나라장터 화면 위에서 바로 확인하려면: {web}/guide\n"
    )
    html = (
        f'<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님, 진단 결과 '
        f'<b>{escape(region)} {escape(industry)}</b> 기준으로 자격이 맞는 공고가 '
        f'<b style="color:#3182F6;">{escape(label)}</b>이었어요.</p>'
        '<p style="font-size:15px;line-height:1.7;color:#4E5968;margin:0 0 20px;">'
        "새 공고는 매일 올라옵니다. 조건에 맞는 건이 뜨면 이어서 알려드릴게요.</p>"
        f"{_btn(f'{web}/diagnose', '내 조건 공고 다시 보기')}"
    )
    return subject, text, html


@register("lead_optin_confirm", "transactional")
def _lead_optin_confirm(ctx: dict) -> tuple[str, str, str]:
    """더블 옵트인 확인 요청 — 주소 소유자에게 "정말 신청하셨나요"를 묻는다.

    **광고를 담지 않는다.** 담는 순간 이 메일 자체가 미확인 주소로 보낸 광고물이 되어
    더블 옵트인을 도입한 이유가 사라진다. 그래서 할인·권유·공고 목록이 없고, 확인
    버튼과 "본인이 아니면 무시하세요" 안내만 있다.
    """
    confirm_url = ctx.get("confirm_url") or ""
    region = ctx.get("region") or ""
    industry = ctx.get("industry") or ""
    who = f"{region} {industry}".strip()

    subject = "수신 신청을 확인해 주세요"
    text = (
        "사장님, 아래 버튼을 눌러 주셔야 조건에 맞는 공고 알림을 보내드릴 수 있어요.\n"
        + (f"신청하신 조건: {who}\n" if who else "")
        + f"\n확인하기: {confirm_url}\n\n"
        "본인이 신청하지 않으셨다면 이 메일을 무시해 주세요. 확인 전에는 아무 알림도 가지 않습니다.\n"
    )
    html = (
        '<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님, 아래 버튼을 눌러 주셔야 '
        "조건에 맞는 공고 알림을 보내드릴 수 있어요.</p>"
        + (
            f'<p style="font-size:15px;line-height:1.7;color:#4E5968;margin:0 0 20px;">'
            f"신청하신 조건: <b>{escape(who)}</b></p>" if who else ""
        )
        + f"{_btn(confirm_url, '수신 신청 확인하기')}"
        '<p style="font-size:13px;line-height:1.6;color:#8B95A1;margin:18px 0 0;">'
        "본인이 신청하지 않으셨다면 이 메일을 무시해 주세요. 확인 전에는 아무 알림도 가지 않습니다.</p>"
    )
    return subject, text, html


@register("lead_new_matches", "marketing")
def _lead_new_matches(ctx: dict) -> tuple[str, str, str]:
    """주기 육성 — 진단 이후 **새로** 올라온 공고 중 조건에 맞는 것만 추린다.

    웰컴에서 "조건에 맞는 건이 뜨면 이어서 알려드릴게요"라고 약속한 것의 이행이다.
    낙찰 가능성·예측은 쓰지 않는다(전역 금지) — '넣을 수 있는가'까지만 말한다.
    """
    region = ctx.get("region") or ""
    industry = ctx.get("industry") or "우리 회사"
    count = int(ctx.get("new_count") or 0)
    notices = ctx.get("notices") or []          # [{title, organization, end_date_label}]
    web = settings.PUBLIC_WEB_URL
    # 매칭 상한(MATCH_LIMIT)에 걸린 값이면 실제로는 더 많다 — 진단 화면의 `capped` 와
    # 같은 정직성 장치. 상한값을 딱 떨어지게 말하면 사실과 다른 수를 말하게 된다.
    label = f"{count}건+" if ctx.get("capped") else f"{count}건"

    subject = f"{region} {industry}, 새로 올라온 공고 {label}이 조건에 맞아요".strip()

    lines = [
        f"사장님, 진단해 드린 조건({region} {industry})에 맞는 공고가 새로 {label} 올라왔어요.",
        "",
    ]
    for n in notices:
        due = n.get("end_date_label") or ""
        org = n.get("organization") or ""
        lines.append(f"· {n.get('title') or ''}" + (f" ({org}, 마감 {due})" if org or due else ""))
    lines += [
        "",
        f"전체 목록 보기: {web}/diagnose",
        "",
        "※ 자격 요건이 맞는지까지만 확인해 드립니다. 낙찰 여부를 예측하지는 않아요.",
        "",
    ]
    text = "\n".join(lines)

    items = "".join(
        '<li style="font-size:15px;line-height:1.7;color:#191F28;margin:0 0 8px;">'
        f"<b>{escape(n.get('title') or '')}</b>"
        + (
            '<br><span style="font-size:13px;color:#8B95A1;">'
            f"{escape(n.get('organization') or '')}"
            + (f" · 마감 {escape(n.get('end_date_label') or '')}" if n.get("end_date_label") else "")
            + "</span>"
        )
        + "</li>"
        for n in notices
    )
    html = (
        f'<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님, 진단해 드린 조건'
        f'(<b>{escape(region)} {escape(industry)}</b>)에 맞는 공고가 새로 '
        f'<b style="color:#3182F6;">{escape(label)}</b> 올라왔어요.</p>'
        f'<ul style="padding-left:18px;margin:0 0 20px;">{items}</ul>'
        f"{_btn(f'{web}/diagnose', '전체 목록 보기')}"
        '<p style="font-size:13px;line-height:1.6;color:#8B95A1;margin:18px 0 0;">'
        "자격 요건이 맞는지까지만 확인해 드립니다. 낙찰 여부를 예측하지는 않아요.</p>"
    )
    return subject, text, html


@register("signup_optin_confirm", "transactional")
def _signup_optin_confirm(ctx: dict) -> tuple[str, str, str]:
    """가입 시 수신동의한 회원의 더블 옵트인 확인 요청.

    리드용(`lead_optin_confirm`)과 문구만 다르다 — 이쪽은 이미 계정이 있는 사람이라
    "가입해 주셔서 감사합니다"가 아니라 **알림 수신 확인**만 묻는다. 광고는 담지 않는다.
    """
    confirm_url = ctx.get("confirm_url") or ""

    subject = "공고 알림 수신을 확인해 주세요"
    text = (
        "사장님, 가입하실 때 체크하신 공고 알림을 보내드리려면 확인이 한 번 필요해요.\n\n"
        f"확인하기: {confirm_url}\n\n"
        "본인이 신청하지 않으셨다면 이 메일을 무시해 주세요. 확인 전에는 알림이 가지 않습니다.\n"
        "결제·체험 만료 같은 거래 관련 안내는 이 확인과 무관하게 발송됩니다.\n"
    )
    html = (
        '<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님, 가입하실 때 체크하신 '
        "<b>공고 알림</b>을 보내드리려면 확인이 한 번 필요해요.</p>"
        f"{_btn(confirm_url, '알림 수신 확인하기')}"
        '<p style="font-size:13px;line-height:1.6;color:#8B95A1;margin:18px 0 0;">'
        "본인이 신청하지 않으셨다면 이 메일을 무시해 주세요. 확인 전에는 알림이 가지 않습니다.<br>"
        "결제·체험 만료 같은 거래 관련 안내는 이 확인과 무관하게 발송됩니다.</p>"
    )
    return subject, text, html


@register("unsub_result", "transactional")
def _unsub_result(ctx: dict) -> tuple[str, str, str]:
    """수신거부 처리 결과 통지 — 정보통신망법 제50조가 요구하는 **법정 고지**.

    광고성 정보 전송자는 수신거부·수신동의 철회 의사를 받으면 그 **처리 결과를 알려야**
    한다. 즉 이 메일은 보내도 되는 정도가 아니라 **보내야 하는** 메일이다.

    ⚠️ 여기에 재동의 유도·할인·서비스 소식을 넣지 말 것. 방금 광고를 거부한 사람에게
    보내는 메일이라, 광고성 문구가 한 줄이라도 섞이면 **거부 의사를 무시한 광고 발송**이
    된다. 처리 사실과 시각만 알린다.
    """
    email = ctx.get("email") or ""
    processed_at = ctx.get("processed_at") or ""

    subject = "광고성 정보 수신거부 처리 결과 안내"
    text = (
        "요청하신 광고성 정보 수신거부가 처리됐어요.\n\n"
        + (f"· 대상: {email}\n" if email else "")
        + (f"· 처리 일시: {processed_at}\n" if processed_at else "")
        + "\n앞으로 광고성 정보는 보내드리지 않습니다.\n"
        "결제·영수증·체험 만료 안내 같은 거래 관련 안내는 수신거부와 무관하게 계속 발송됩니다.\n"
    )
    rows = "".join(
        f'<p style="font-size:15px;line-height:1.7;color:#4E5968;margin:0 0 6px;">· {label} '
        f"<b>{escape(value)}</b></p>"
        for label, value in (("대상", email), ("처리 일시", processed_at))
        if value
    )
    html = (
        '<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">요청하신 '
        "<b>광고성 정보 수신거부</b>가 처리됐어요.</p>"
        f"{rows}"
        '<p style="font-size:15px;line-height:1.7;color:#4E5968;margin:16px 0 0;">'
        "앞으로 광고성 정보는 보내드리지 않습니다.<br>"
        "결제·영수증·체험 만료 안내 같은 거래 관련 안내는 수신거부와 무관하게 계속 발송됩니다.</p>"
    )
    return subject, text, html


# ── 체험 라이프사이클 (docs/GROWTH_STRATEGY.md §C3) ──
# 카테고리 배치가 이 시퀀스의 핵심이다. **체험 종료 고지는 거래**(동의 불요, 전원 대상)이고
# **할인·권유는 광고**(동의 필요)다. 하나의 메일에 섞으면 그 메일 전체가 광고물이 되어,
# 미동의자에게 보낸 순간 위법 발송이 된다(CLAUDE.md 함정 #10).
@register("trial_welcome", "transactional")
def _trial_welcome(ctx: dict) -> tuple[str, str, str]:
    """D0 — 체험 시작 안내 + 프로필 완성 유도.

    거래성인 이유: 방금 시작한 서비스의 **이용 안내**다. 프로필(면허·지역)이 없으면
    자격 판정 자체가 '판정 불가'로 나오므로, 이 안내는 광고가 아니라 기능 설명이다.
    할인·구매 권유를 넣는 순간 광고가 되므로 넣지 않는다.
    """
    days = int(ctx.get("trial_days") or 14)
    needs_profile = bool(ctx.get("needs_profile"))
    web = settings.PUBLIC_WEB_URL

    subject = f"Pro 체험 {days}일이 시작됐어요"
    profile_line = (
        "면허·지역을 넣으시면 '이 공고에 넣을 수 있는지'를 바로 판정해 드려요. 30초면 됩니다.\n"
        if needs_profile else
        "등록하신 면허·지역 기준으로 자격 판정이 이미 켜져 있어요.\n"
    )
    text = (
        f"사장님, 오늘부터 {days}일 동안 Pro 기능을 카드 등록 없이 쓰실 수 있어요.\n\n"
        f"{profile_line}"
        "\nBidEasy 는 낙찰가를 예측하지 않습니다. 대신 무효·적자 입찰을 막는 데 집중해요.\n"
        f"\n내 조건 설정하기: {web}/account\n"
    )
    html = (
        f'<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님, 오늘부터 '
        f'<b style="color:#3182F6;">{days}일</b> 동안 Pro 기능을 카드 등록 없이 쓰실 수 있어요.</p>'
        f'<p style="font-size:15px;line-height:1.7;color:#4E5968;margin:0 0 20px;">{escape(profile_line.strip())}</p>'
        f"{_btn(f'{web}/account', '내 조건 설정하기')}"
        '<p style="font-size:13px;line-height:1.6;color:#8B95A1;margin:18px 0 0;">'
        "BidEasy 는 낙찰가를 예측하지 않습니다. 대신 무효·적자 입찰을 막는 데 집중해요.</p>"
    )
    return subject, text, html


@register("trial_daily_matches", "marketing")
def _trial_daily_matches(ctx: dict) -> tuple[str, str, str]:
    """D1 — 자격 PASS 공고를 처음 보여준다(첫 가치 경험)."""
    count = int(ctx.get("matched_count") or 0)
    notices = ctx.get("notices") or []
    web = settings.PUBLIC_WEB_URL
    label = f"{count}건+" if ctx.get("capped") else f"{count}건"

    subject = f"오늘 사장님 자격으로 넣을 수 있는 공고 {label}"
    lines = [f"사장님 조건으로 지금 입찰 가능한 공고가 {label} 있어요.", ""]
    for n in notices:
        due = n.get("end_date_label") or ""
        lines.append(f"· {n.get('title') or ''}" + (f" (마감 {due})" if due else ""))
    lines += ["", f"전체 보기: {web}/dashboard", "",
              "※ 자격 요건이 맞는지까지만 확인해 드립니다. 낙찰 여부를 예측하지는 않아요.", ""]

    items = "".join(
        '<li style="font-size:15px;line-height:1.7;margin:0 0 8px;">'
        f"<b>{escape(n.get('title') or '')}</b>"
        + (f'<br><span style="font-size:13px;color:#8B95A1;">마감 {escape(n.get("end_date_label") or "")}</span>'
           if n.get("end_date_label") else "")
        + "</li>"
        for n in notices
    )
    html = (
        f'<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님 조건으로 지금 입찰 가능한 공고가 '
        f'<b style="color:#3182F6;">{escape(label)}</b> 있어요.</p>'
        f'<ul style="padding-left:18px;margin:0 0 20px;">{items}</ul>'
        f"{_btn(f'{web}/dashboard', '전체 공고 보기')}"
        '<p style="font-size:13px;line-height:1.6;color:#8B95A1;margin:18px 0 0;">'
        "자격 요건이 맞는지까지만 확인해 드립니다. 낙찰 여부를 예측하지는 않아요.</p>"
    )
    return subject, "\n".join(lines), html


@register("trial_extension_guide", "marketing")
def _trial_extension_guide(ctx: dict) -> tuple[str, str, str]:
    """D3 — 아직 안 써본 분에게 익스텐션 안내(습관화)."""
    web = settings.PUBLIC_WEB_URL

    subject = "나라장터 화면에서 바로 확인하는 방법"
    text = (
        "사장님, 나라장터에서 공고를 보실 때 창을 옮겨 다니지 않아도 돼요.\n"
        "크롬 확장 프로그램을 설치하시면 보고 계신 공고 위에 자격 판정과 안전 투찰 구간이 바로 뜹니다.\n\n"
        f"설치 방법 보기: {web}/guide\n"
    )
    html = (
        '<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님, 나라장터에서 공고를 보실 때 '
        "창을 옮겨 다니지 않아도 돼요.</p>"
        '<p style="font-size:15px;line-height:1.7;color:#4E5968;margin:0 0 20px;">'
        "크롬 확장 프로그램을 설치하시면 <b>보고 계신 공고 위에</b> 자격 판정과 안전 투찰 구간이 바로 뜹니다.</p>"
        f"{_btn(f'{web}/guide', '설치 방법 보기')}"
    )
    return subject, text, html


@register("trial_value_recap", "marketing")
def _trial_value_recap(ctx: dict) -> tuple[str, str, str]:
    """D7 — 체험 절반 시점의 사용 요약(가치 각인).

    숫자는 **실제 사용 기록**만 쓴다. 없으면 없다고 말한다 — 지어낸 성과는 신뢰를 깎는다.
    """
    checks = int(ctx.get("check_count") or 0)
    favorites = int(ctx.get("favorite_count") or 0)
    web = settings.PUBLIC_WEB_URL

    subject = "체험 절반이 지났어요 — 지금까지 확인하신 것들"
    if checks or favorites:
        body_line = f"지금까지 투찰 계산 {checks}회, 관심 공고 {favorites}건을 담아두셨어요."
    else:
        body_line = "아직 확인해 보신 공고가 없네요. 한 건만 넣어보셔도 판정이 바로 나와요."
    text = (
        f"사장님, {body_line}\n\n"
        "무효 입찰은 한 번이면 그 건을 통째로 잃습니다. 넣기 전에 30초만 확인해 보세요.\n"
        f"\n내 대시보드: {web}/dashboard\n"
    )
    html = (
        f'<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님, {escape(body_line)}</p>'
        '<p style="font-size:15px;line-height:1.7;color:#4E5968;margin:0 0 20px;">'
        "무효 입찰은 한 번이면 그 건을 통째로 잃습니다. 넣기 전에 30초만 확인해 보세요.</p>"
        f"{_btn(f'{web}/dashboard', '내 대시보드 열기')}"
    )
    return subject, text, html


@register("trial_winback", "marketing")
def _trial_winback(ctx: dict) -> tuple[str, str, str]:
    """체험 만료 직후 — 할인 안내. **광고다**(할인은 그 자체로 광고성 정보).

    그래서 미동의자에게는 나가지 않는다. 만료 '사실'은 거래 템플릿(`trial_expiry`)이
    이미 전원에게 알렸으므로, 미동의자가 정보를 놓치는 일은 없다.
    """
    price = ctx.get("discount_price") or ""
    days = int(ctx.get("grace_days") or 7)
    web = settings.PUBLIC_WEB_URL

    subject = f"체험 종료 후 {days}일 안에는 첫 달 반값이에요"
    text = (
        f"사장님, Pro 체험이 끝났지만 {days}일 안에 시작하시면 첫 달을 절반 가격으로 쓰실 수 있어요.\n"
        + (f"첫 달 {price}\n" if price else "")
        + "\n무효 입찰 한 번이면 1년 구독료가 회수됩니다.\n"
        f"\n요금제 보기: {web}/pricing\n"
    )
    html = (
        f'<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">사장님, Pro 체험이 끝났지만 '
        f'<b>{days}일</b> 안에 시작하시면 <b style="color:#3182F6;">첫 달을 절반 가격</b>으로 쓰실 수 있어요.</p>'
        + (f'<p style="font-size:15px;line-height:1.7;color:#4E5968;margin:0 0 20px;">첫 달 '
           f"<b>{escape(str(price))}</b></p>" if price else "")
        + f"{_btn(f'{web}/pricing', '요금제 보기')}"
        '<p style="font-size:13px;line-height:1.6;color:#8B95A1;margin:18px 0 0;">'
        "무효 입찰 한 번이면 1년 구독료가 회수됩니다.</p>"
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
