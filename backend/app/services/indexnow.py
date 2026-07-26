"""IndexNow — 새 URL·변경 URL 을 검색엔진에 직접 통보.

사이트맵이 "여기 목록이 있으니 언젠가 보라"라면, IndexNow 는 "이 URL 이 지금
생겼다"를 즉시 알린다. 네이버가 2023-07 부터 지원하며 서치어드바이저 로그인
없이 키만 공개해 두면 동작한다 — 우리 비치헤드(네이버 주 사용)에 직접 효과.

전제(정직): 이건 **통보이지 색인 보장이 아니다.** 반영 여부·시점은 검색엔진이
정한다. 효과는 서치어드바이저 수집 현황으로 사후 확인해야 한다.

키는 비밀이 아니다 — 프로토콜상 `https://bideasy.kr/{key}.txt` 로 **공개**해야
소유 증명이 성립한다. config 기본값과 `infra/nginx/html/{key}.txt` 는 같은 값을
유지해야 한다.
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SITE_URL = "https://bideasy.kr"
# 프로토콜 상한(POST 1회 10,000 URL). 실제로는 아래 MAX_PER_RUN 이 먼저 걸린다.
CHUNK_SIZE = 10_000
# 한 번의 호출로 쏘는 총량 상한 — 일일 훅이 폭주해도 검색엔진에 도배하지 않도록.
MAX_PER_RUN = 2_000
TIMEOUT_SECONDS = 10.0


def is_enabled() -> bool:
    """운영 환경 + 키 설정이 모두 참일 때만 발송.

    dev/test 에서 실제 검색엔진에 쏘면 안 되므로 APP_ENV 를 함께 본다.
    """
    return bool(settings.INDEXNOW_KEY) and settings.APP_ENV == "production"


def notice_urls(bid_nos) -> list[str]:
    return [f"{SITE_URL}/bid/{b}" for b in bid_nos if b]


def blog_urls(slugs) -> list[str]:
    return [f"{SITE_URL}/blog/{s}" for s in slugs if s]


def _clean(urls, cap: int) -> list[str]:
    """자기 호스트 URL 만, 순서 유지 중복 제거, 상한 적용."""
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if not u or not str(u).startswith(SITE_URL + "/"):
            continue
        u = str(u)
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= cap:
            break
    return out


def submit(urls, *, reason: str = "", max_urls: int | None = None) -> dict:
    """URL 목록을 참여 검색엔진에 통보. **절대 예외를 올리지 않는다**(best-effort).

    호출부(발행·수집)는 이미 성공한 작업이므로, 통보 실패가 그 작업을 되돌리게
    해서는 안 된다. 실패는 로그로만 남긴다.

    max_urls: 회당 상한 override. 기본(None)은 MAX_PER_RUN — 자동 훅이 폭주해도
    도배하지 않게 하는 안전장치다. 의도적인 일회성 일괄 통보(backfill)처럼
    "전량을 보내는 게 목적"인 호출만 명시적으로 올린다.
    """
    if not is_enabled():
        return {"skipped": "disabled", "count": 0}

    targets = _clean(urls, max_urls if max_urls is not None else MAX_PER_RUN)
    if not targets:
        return {"skipped": "no_urls", "count": 0}

    key = settings.INDEXNOW_KEY
    results: dict[str, str] = {}
    for endpoint in settings.INDEXNOW_ENDPOINTS:
        try:
            for start in range(0, len(targets), CHUNK_SIZE):
                resp = httpx.post(
                    endpoint,
                    json={
                        "host": SITE_URL.replace("https://", ""),
                        "key": key,
                        "keyLocation": f"{SITE_URL}/{key}.txt",
                        "urlList": targets[start:start + CHUNK_SIZE],
                    },
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    timeout=TIMEOUT_SECONDS,
                )
                results[endpoint] = str(resp.status_code)
                # 200 OK / 202 Accepted(키 검증 대기) 모두 정상 경로.
                if resp.status_code not in (200, 202):
                    logger.warning(
                        f"[indexnow] {endpoint} → {resp.status_code} "
                        f"(count={len(targets)} reason={reason})"
                    )
        except Exception as e:  # 네트워크·타임아웃 등 — 통보 실패는 비치명적
            results[endpoint] = f"error: {e}"
            logger.warning(f"[indexnow] {endpoint} 실패: {e}")

    logger.info(f"[indexnow] submitted={len(targets)} reason={reason} results={results}")
    return {"count": len(targets), "results": results}
