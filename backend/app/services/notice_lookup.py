"""공고번호 → DB 정본 Notice 해소 규칙 — 단일 소스.

context(receipt 발급)와 growth(활성화 검증)가 같은 입력을 서로 다른 공고로 풀면
receipt 가 영영 맞지 않는다(2026-08-17 리뷰: 한쪽은 오름차순, 한쪽은 내림차순으로
차수를 골라 재공고에서 활성화 POST 가 영구 403 이었다). 규칙은 여기 한 곳에만 둔다.

규칙:
1. 공백 제거 후 정확 일치.
2. 차수(`-000`)까지 들어온 정본 ID 가 없으면 **다른 차수로 조용히 바꾸지 않는다**.
3. 차수가 아예 없는 입력만 같은 base 의 **최신 차수(내림차순)** 로 결정적으로 보완한다.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.db import models

# LIKE wildcard 가 실제 공고로 해석되면 임의 입력이 첫 캐시 공고의 context 와
# activation receipt 를 받을 수 있다. 나라장터 공고번호 문자만 허용한다.
BID_NO_RE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
BID_NO_MAX_LEN = 100


def normalize_bid_no(raw: str) -> str:
    """공백 제거 + 표시형식(...-000) 통일. DB 는 'bidNtceNo-bidNtceOrd' 로 저장."""
    return re.sub(r"\s+", "", raw or "")


def is_valid_bid_no(raw: str) -> bool:
    normalized = normalize_bid_no(raw)
    return bool(normalized and len(normalized) <= BID_NO_MAX_LEN and BID_NO_RE.fullmatch(normalized))


def resolve_notice(db: Session, bid_no: str) -> Optional[models.Notice]:
    """정본 규칙으로 Notice 행을 돌려준다. 없거나 형식이 틀리면 None."""
    norm = normalize_bid_no(bid_no)
    if not is_valid_bid_no(norm):
        return None
    notice = db.query(models.Notice).filter(models.Notice.bid_no == norm).first()
    if notice is not None:
        return notice
    if "-" in norm:
        return None
    return (
        db.query(models.Notice)
        .filter(models.Notice.bid_no.like(f"{norm}-%"))
        .order_by(models.Notice.bid_no.desc())
        .first()
    )


def resolve_bid_no(db: Session, bid_no: str) -> Optional[str]:
    """정본 규칙으로 DB 공고번호 문자열만 돌려준다 (행이 필요 없을 때)."""
    notice = resolve_notice(db, bid_no)
    return str(notice.bid_no) if notice is not None else None
