"""계산 결과 공유 — 링크 미리보기(og:image)용 숫자 카드.

카톡·네이버 블로그/카페 링크 카드는 JS 를 실행하지 않으므로 서버가 숫자를 그린다.
공식은 웹 계산기(calculator.html render())와 같아야 한다 — 링크를 연 사람이 같은
숫자를 봐야 하기 때문. 하한선 판정은 공사만 낸다(용역·물품은 계산기도 별도 정책).
"""
import io
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.services.lower_limits import is_plausible_rate, lower_limit_from_basis

_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
CT_LABEL = {"CONSTRUCTION": "공사", "SERVICE": "용역", "GOODS": "물품"}
MAX_BASIC = 10_000_000_000_000  # 10조 — 이 위는 오타로 본다


def parse(ct: str | None, basic: str | None, tcl: str | None, a: str | None,
          a_src: str | None = None, llr: str | None = None) -> dict | None:
    """쿼리 파라미터 검증. 하나라도 이상하면 None (카드 대신 기본 계산기로 보낸다)."""
    try:
        ct = (ct or "CONSTRUCTION").upper()
        basic_v = int(float(basic))
        tcl_v = round(float(tcl), 3)
        a_v = int(float(a or 0)) if ct != "GOODS" else 0
    except (TypeError, ValueError, OverflowError):
        return None
    # 투찰률 범위는 웹 계산기 슬라이더(85~92)와 같다 — 밖이면 계산기가 무시해 숫자가 갈라진다
    if ct not in CT_LABEL or not (0 < basic_v <= MAX_BASIC) or not (85 <= tcl_v <= 92) \
            or not (0 <= a_v < basic_v):
        return None
    est = a_src == "median" and a_v > 0
    try:
        llr_v = round(float(llr), 3) if llr not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        llr_v = None
    # 공고 명시 하한율(계산기가 공고를 불러온 경우) — 범위 밖이면 버리고 기초금액 판정으로
    llr_v = llr_v if is_plausible_rate(llr_v) else None
    return {"ct": ct, "basic": basic_v, "tcl": tcl_v, "a": a_v, "a_est": est, "llr": llr_v}


def compute(p: dict) -> dict:
    basic, tcl, a = p["basic"], p["tcl"], p["a"]
    predicted = math.floor(((basic - a) * (tcl / 100) + a) / 10) * 10
    out = {**p, "predicted": predicted, "rate": None, "lower": None, "diff": None, "level": None,
           "ambiguous": False}
    if p["ct"] == "CONSTRUCTION":
        # 웹 계산기와 같은 규칙: 공고 하한율이 있으면 그것, 없으면 기초금액 보수 판정(BD_LOWER.fromBasis)
        if p.get("llr"):
            rate, ambiguous = p["llr"], False
        else:
            rate, ambiguous = lower_limit_from_basis("CONSTRUCTION", basic)
        out["ambiguous"] = ambiguous
        lower = math.floor((basic - a) * rate / 100 + a + 0.5)  # JS Math.round 와 같은 0.5 올림
        diff = (predicted - lower) / basic * 100
        level = "DANGER" if predicted < lower else ("WARN" if diff < 0.5 else "SAFE")
        out.update(rate=rate, lower=lower, diff=round(diff, 2), level=level)
    return out


def won(n: int) -> str:
    return f"{n:,}"


def eok(n: int) -> str:
    """5억 · 1,240만 처럼 읽기 쉬운 금액."""
    if n >= 100_000_000:
        v = n / 100_000_000
        return f"{v:g}억" if v == int(v) else f"{v:.2f}".rstrip("0").rstrip(".") + "억"
    return f"{n // 10_000:,}만"


def summary_line(r: dict) -> str:
    tcl = f"{r['tcl']:.3f}".rstrip("0").rstrip(".")  # 89.745 는 그대로, 90.300 은 90.3
    parts = [f"기초금액 {eok(r['basic'])}", f"투찰률 {tcl}%"]
    if r["a"]:
        parts.append(f"A값{'(추정)' if r.get('a_est') else ''} {eok(r['a'])}")
    return " · ".join(parts)


def verdict(r: dict) -> str:
    if r["level"] is None:
        return ""
    sign = "+" if r["diff"] >= 0 else ""
    return {"SAFE": "하한선 이상", "WARN": "하한선 근접", "DANGER": "하한선 미달"}[r["level"]] \
        + f" {sign}{r['diff']:.2f}%p"


@lru_cache(maxsize=16)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_DIR / name), size)


@lru_cache(maxsize=256)
def render_png(ct: str, basic: int, tcl: float, a: int, a_est: bool = False,
               llr: float | None = None) -> bytes:
    r = compute({"ct": ct, "basic": basic, "tcl": tcl, "a": a, "a_est": a_est, "llr": llr})
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (49, 130, 246))
    d = ImageDraw.Draw(img)
    bold = lambda s: _font("Pretendard-Bold.otf", s)  # noqa: E731
    reg = lambda s: _font("Pretendard-Regular.otf", s)  # noqa: E731
    white, soft = (255, 255, 255), (214, 230, 255)
    d.text((72, 64), f"BidEasy 투찰가 계산 · {CT_LABEL[ct]}", font=bold(36), fill=soft)
    d.text((72, 150), f"₩{won(r['predicted'])}", font=bold(112), fill=white)
    d.text((72, 300), summary_line(r), font=reg(40), fill=white)
    v = verdict(r)
    if v:
        color = {"SAFE": (52, 199, 89), "WARN": (255, 149, 0), "DANGER": (255, 59, 48)}[r["level"]]
        tw = d.textlength(v, font=bold(40))
        d.rounded_rectangle((72, 380, 72 + tw + 48, 452), radius=36, fill=white)
        d.text((96, 391), v, font=bold(40), fill=color)
        note = " (추정가격 구간 확인 필요)" if r["ambiguous"] else (" (공고 명시)" if r.get("llr") else "")
        d.text((72, 470), f"낙찰하한선 {r['rate']}% · ₩{won(r['lower'])}{note}", font=reg(34), fill=soft)
    else:
        d.text((72, 390), "하한율은 공고문에서 확인하세요 (용역·물품은 계약 방식마다 다름)", font=reg(34), fill=soft)
    d.rectangle((0, H - 84, W, H), fill=(25, 31, 40))
    d.text((72, H - 64), "bideasy.kr/calculator  ·  낙찰가를 예측하지 않습니다", font=reg(32), fill=soft)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
