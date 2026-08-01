"""리드 자격 매칭 — 진단 화면과 육성 메일이 **같은 기준**을 쓰게 하는 단일 소스.

왜 서비스로 뺐나
----------------
진단(`POST /leads/diagnose`)에서 "넣을 수 있는 공고 12건"이라고 보여준 뒤, 며칠 후
육성 메일이 다른 기준으로 고른 공고를 보내면 사용자는 우리 판정을 믿지 않게 된다.
"안전 비서"의 자산은 정확도가 아니라 **일관성**이므로 판정 로직을 한 곳에 둔다.

`since` 를 주면 그 시각 이후 **새로 올라온** 공고만 본다 — 육성 메일이 이미 보여준
공고를 다시 보내지 않게 하는 장치다. 진단은 `since=None`(활성 전체)로 부른다.

콜드-DB 워밍은 여기 없다. 워밍은 "실방문자에게 0건이 오인 표시되는 것"을 막는
**진단 화면 전용 관심사**이고(`endpoints/leads.py`), 배치 태스크는 일일 크롤 이후에
돌기 때문에 워밍이 필요 없다.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db import models
from app.services.qualification_checker import QualificationChecker

# 진단 스캔·반환 상한 (성능 보호)
SCAN_LIMIT = 500      # 자격 판정할 후보 공고 최대 스캔 수
MATCH_LIMIT = 50      # 반환할 매칭 공고 최대 수

# 업종·면허 텍스트에서 대표 면허 루트 키워드 추출용
# (QualificationChecker 가 공고 제목에서 인식하는 키워드와 정합)
LICENSE_ROOTS = ["전기", "정보통신", "통신", "소방", "건축", "토목"]


def detect_root(*texts: Optional[str]) -> Optional[str]:
    """업종·면허 문자열에서 대표 면허 루트 키워드 1개 추출(없으면 None)."""
    blob = " ".join(t for t in texts if t)
    for root in LICENSE_ROOTS:
        if root in blob:
            return root
    return None


def pseudo_profile(industry: Optional[str], licenses: Optional[str], region: Optional[str]):
    """QualificationChecker 가 기대하는 사용자 프로필의 최소 형태.

    리드는 로그인 사용자가 아니므로 실제 User 행이 없다. 판정에 쓰이는 두 속성만
    채운 가상 프로필로 대신한다.
    """
    return SimpleNamespace(location=(region or ""), licenses=(licenses or industry or ""))


def match_notices(
    db: Session,
    industry: Optional[str],
    licenses: Optional[str],
    region: Optional[str],
    *,
    since: Optional[datetime] = None,
    scan_limit: int = SCAN_LIMIT,
    match_limit: int = MATCH_LIMIT,
) -> List[models.Notice]:
    """활성 공고를 QualificationChecker 로 필터해 자격 PASS 공고만 반환.

    업종 루트 키워드가 있으면 후보를 그 공종으로 좁혀 '내 공종의 넣을 수 있는 공고'로
    정밀화한다. `since` 를 주면 그 이후 등록된 공고만 본다(육성 메일의 "신규" 기준).
    """
    pseudo = pseudo_profile(industry, licenses, region)

    q = db.query(models.Notice).filter(~models.Notice.title.like("[Mock]%"))
    q = q.filter(models.Notice.end_date > datetime.now())  # 활성(마감 전)만
    if since is not None:
        q = q.filter(models.Notice.start_date >= since)

    root = detect_root(industry, licenses)
    if root:
        q = q.filter(models.Notice.title.ilike(f"%{root}%"))

    candidates = q.order_by(models.Notice.end_date.asc()).limit(scan_limit).all()

    matched: List[models.Notice] = []
    for n in candidates:
        notice_dict = {"bidNtceNm": n.title or "", "LmtRegion": n.region or ""}
        res = QualificationChecker.check_qualification(notice_dict, pseudo)
        if res.get("status") == "PASS":
            matched.append(n)
            if len(matched) >= match_limit:
                break
    return matched
