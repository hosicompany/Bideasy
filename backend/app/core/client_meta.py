"""요청자 메타(IP·User-Agent) 추출 — 레이트리밋·동의 증적 공용.

두 곳이 같은 판단을 필요로 한다:
  - 레이트리밋: "이 요청자가 누구인가"(어뷰징 차단)
  - 동의 증적: "누가·어디서 동의했는가"(정보통신망법 제50조 증명책임)
따라서 IP 판정 로직은 한 곳에만 둔다. 두 벌이 되면 한쪽만 XFF 스푸핑에 뚫린다.
"""
from typing import Optional

from fastapi import Request

# consent_records.user_agent / leads.consent_user_agent 컬럼 길이와 일치
_UA_MAX = 300


def client_ip(request: Request) -> str:
    """프록시(nginx) 뒤 실 IP.

    ⚠️ XFF 의 첫 요소는 클라이언트가 위조할 수 있다. nginx 는
    `$proxy_add_x_forwarded_for` 로 실 IP 를 **맨 뒤**에 append 하므로,
    신뢰 프록시(1단)가 붙인 마지막 요소를 실 클라이언트 IP 로 사용한다.
    (첫 요소를 쓰면 XFF 스푸핑으로 레이트리밋이 통째로 우회됨)
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def user_agent(request: Request) -> Optional[str]:
    """User-Agent 헤더(증적 보관용, 컬럼 길이로 절단). 없으면 None."""
    ua = request.headers.get("user-agent")
    return ua[:_UA_MAX] if ua else None
