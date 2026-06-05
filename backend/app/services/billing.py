"""토스페이먼츠 자동결제(빌링) 서비스.

빌링 플로우:
  1. [프론트] tossPayments.requestBillingAuth('카드', {customerKey, successUrl, failUrl})
       → 사용자가 카드 등록 → successUrl 로 ?customerKey=&authKey= 리다이렉트
  2. [백엔드] issue_billing_key(authKey, customerKey)
       → POST /v1/billing/authorizations/issue → billingKey 발급 (영구 보관)
  3. [백엔드] charge_billing_key(billingKey, ...)
       → POST /v1/billing/{billingKey} → 즉시 청구 (첫 결제 + 매 주기 자동청구)

엔드포인트(콜백)와 Celery 자동갱신 task 가 공용으로 호출하므로 sync httpx 사용.
(Celery worker 는 동기 컨텍스트, FastAPI 콜백은 run_in_threadpool 로 감싸 호출)
"""
from __future__ import annotations

from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

TOSS_BILLING_AUTH_ISSUE_URL = "https://api.tosspayments.com/v1/billing/authorizations/issue"
TOSS_BILLING_CHARGE_URL = "https://api.tosspayments.com/v1/billing/{billing_key}"

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class BillingError(Exception):
    """토스 빌링 API 오류 — code/message 보존."""

    def __init__(self, message: str, code: str = "", status_code: int = 0):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def _mask_card(card: Optional[dict]) -> str:
    """토스 card 응답 → 표시용 마스킹 문자열. 예) '신한 ****1234'.

    card.number 는 이미 마스킹된 값('123456******1234' 형태)일 수 있어
    끝 4자리만 추출. issuerCode 는 카드사 코드(숫자) — 매핑 없으면 코드 그대로.
    """
    if not card:
        return ""
    number = (card.get("number") or "").replace("*", "").replace("-", "")
    last4 = number[-4:] if len(number) >= 4 else number
    issuer = card.get("issuerCode") or card.get("acquirerCode") or ""
    name = _ISSUER_NAMES.get(str(issuer), "")
    label = name or (f"카드사{issuer}" if issuer else "카드")
    return f"{label} ****{last4}".strip()


# 토스 카드사 코드 → 표시명 (주요사만; 미등록 코드는 코드 그대로 노출)
_ISSUER_NAMES = {
    "11": "국민", "31": "BC", "51": "삼성", "61": "현대", "71": "롯데",
    "41": "신한", "21": "하나", "91": "농협", "32": "광주", "34": "수협",
    "35": "전북", "36": "씨티", "37": "우리", "33": "우체국", "38": "새마을",
    "39": "저축", "40": "제주", "42": "신협", "43": "K뱅크", "44": "카카오뱅크",
}


def issue_billing_key(auth_key: str, customer_key: str) -> dict:
    """authKey + customerKey → 빌링키 발급.

    Returns: { "billingKey", "card_display", "method", "raw" }
    Raises: BillingError
    """
    try:
        resp = httpx.post(
            TOSS_BILLING_AUTH_ISSUE_URL,
            json={"authKey": auth_key, "customerKey": customer_key},
            auth=(settings.toss_billing_secret_key, ""),
            headers={"Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as e:
        logger.error(f"Billing issue network error: {e}")
        raise BillingError("빌링키 발급 통신 오류", code="NETWORK", status_code=0)

    if resp.status_code != 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        code = data.get("code", "")
        msg = data.get("message", "빌링키 발급에 실패했습니다")
        logger.warning(f"Billing issue failed: {resp.status_code} code={code} msg={msg}")
        raise BillingError(msg, code=code, status_code=resp.status_code)

    data = resp.json()
    return {
        "billingKey": data.get("billingKey", ""),
        "card_display": _mask_card(data.get("card")),
        "method": data.get("method", "카드"),
        "raw": data,
    }


def charge_billing_key(
    *,
    billing_key: str,
    customer_key: str,
    amount: int,
    order_id: str,
    order_name: str,
    customer_email: Optional[str] = None,
    customer_name: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    """빌링키로 즉시 청구.

    Returns: { "paymentKey", "status", "method", "raw" }
    Raises: BillingError (status != 200 또는 status != DONE)
    """
    body: dict = {
        "customerKey": customer_key,
        "amount": amount,
        "orderId": order_id,
        "orderName": order_name,
    }
    if customer_email:
        body["customerEmail"] = customer_email
    if customer_name:
        body["customerName"] = customer_name

    headers = {"Content-Type": "application/json"}
    # Idempotency-Key — 동일 키 재요청 시 토스가 중복청구 방지 (네트워크 재시도 안전)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key[:300]

    url = TOSS_BILLING_CHARGE_URL.format(billing_key=billing_key)
    try:
        resp = httpx.post(
            url,
            json=body,
            auth=(settings.toss_billing_secret_key, ""),
            headers=headers,
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as e:
        logger.error(f"Billing charge network error: order={order_id}: {e}")
        raise BillingError("자동결제 통신 오류", code="NETWORK", status_code=0)

    try:
        data = resp.json()
    except Exception:
        data = {}

    if resp.status_code != 200:
        code = data.get("code", "")
        msg = data.get("message", "자동결제에 실패했습니다")
        logger.warning(
            f"Billing charge failed: order={order_id} {resp.status_code} "
            f"code={code} msg={msg}"
        )
        raise BillingError(msg, code=code, status_code=resp.status_code)

    status = data.get("status", "")
    if status not in ("DONE", "WAITING_FOR_DEPOSIT"):
        msg = data.get("message", f"결제 상태 이상: {status}")
        logger.warning(f"Billing charge unexpected status: order={order_id} status={status}")
        raise BillingError(msg, code=status, status_code=resp.status_code)

    return {
        "paymentKey": data.get("paymentKey", ""),
        "status": status,
        "method": data.get("method", "카드"),
        "raw": data,
    }
