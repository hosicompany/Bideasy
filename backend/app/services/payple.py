"""페이플(Payple) 국내카드 정기결제(빌링) 서비스.

흐름:
  1. [프론트] payment.js + PaypleCpayAuthCheck({clientKey, PCD_PAY_WORK:'CERT'})
     → 카드 등록 + 첫 청구 → PCD_RST_URL(백엔드 콜백)로 결과 전송.
     콜백에 PCD_PAYER_ID(=빌링키) 포함.
  2. [백엔드] 빌링키 저장 후 정기청구는 서버에서:
     - partner_auth("PAYM") → PCD_AUTH_KEY
     - SimplePayCardAct.php?ACT_=PAYM 에 PCD_PAYER_ID+금액 → 청구

토스 billing.py 와 동일하게 sync httpx (콜백·Celery 공용).
"""
import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class PaypleError(Exception):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code


def _headers() -> dict:
    # Referer 가 페이플 등록 도메인과 일치해야 함 (불일치 시 AUTH0004)
    return {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "Referer": settings.PAYPLE_REFERER,
    }


def partner_auth(pay_work: str = None) -> dict:
    """파트너 인증 → PCD_AUTH_KEY 등 세션 정보 반환."""
    body = {
        "cst_id": settings.PAYPLE_CST_ID,
        "custKey": settings.PAYPLE_CUST_KEY,
        "PCD_PAY_TYPE": "card",
        "PCD_SIMPLE_FLAG": "Y",
    }
    if pay_work:
        body["PCD_PAY_WORK"] = pay_work
    try:
        resp = httpx.post(
            f"{settings.payple_host}/php/auth.php", json=body, headers=_headers(), timeout=_TIMEOUT
        )
    except httpx.HTTPError as e:
        logger.error(f"payple auth network error: {e}")
        raise PaypleError("페이플 인증 통신 오류", code="NETWORK")
    try:
        data = resp.json()
    except Exception:
        data = {}
    auth_key = data.get("AuthKey") or data.get("PCD_AUTH_KEY")
    if not auth_key and str(data.get("result", "")).lower() != "success":
        logger.warning(f"payple auth failed: {data}")
        raise PaypleError(data.get("result_msg") or "페이플 인증 실패", code=str(data.get("result", "")))
    return data


def charge_billing(*, payer_id: str, amount: int, oid: str, goods: str,
                   payer_name: str = None, payer_email: str = None) -> dict:
    """빌링키(PCD_PAYER_ID)로 정기청구. 성공 시 응답 dict, 실패 시 PaypleError."""
    auth = partner_auth(pay_work="PAYM")
    auth_key = auth.get("AuthKey") or auth.get("PCD_AUTH_KEY")
    cst_id = auth.get("cst_id") or settings.PAYPLE_CST_ID
    cust_key = auth.get("custKey") or settings.PAYPLE_CUST_KEY
    host = auth.get("PCD_PAY_HOST") or settings.payple_host
    url = auth.get("PCD_PAY_URL") or "/php/SimplePayCardAct.php?ACT_=PAYM"
    if not url.startswith("http"):
        url = host.rstrip("/") + ("/" + url.lstrip("/"))

    body = {
        "PCD_CST_ID": cst_id,
        "PCD_CUST_KEY": cust_key,
        "PCD_AUTH_KEY": auth_key,
        "PCD_PAY_TYPE": "card",
        "PCD_PAYER_ID": payer_id,
        "PCD_PAY_GOODS": goods,
        "PCD_PAY_TOTAL": str(int(amount)),
        "PCD_PAY_OID": oid,
        "PCD_SIMPLE_FLAG": "Y",
    }
    if payer_name:
        body["PCD_PAYER_NAME"] = payer_name
    if payer_email:
        body["PCD_PAYER_EMAIL"] = payer_email

    try:
        resp = httpx.post(url, json=body, headers=_headers(), timeout=_TIMEOUT)
    except httpx.HTTPError as e:
        logger.error(f"payple charge network error: {e}")
        raise PaypleError("페이플 청구 통신 오류", code="NETWORK")
    try:
        data = resp.json()
    except Exception:
        data = {}
    rst = str(data.get("PCD_PAY_RST", "")).lower()
    if rst != "success":
        logger.warning(f"payple charge failed: oid={oid} {data.get('PCD_PAY_CODE')} {data.get('PCD_PAY_MSG')}")
        raise PaypleError(data.get("PCD_PAY_MSG") or "페이플 청구 실패", code=str(data.get("PCD_PAY_CODE", rst)))
    return data


def card_display(data: dict) -> str:
    """콜백/청구 응답 → 표시용 카드 문자열. 예) '신한카드 ****1234'."""
    name = data.get("PCD_PAY_CARDNAME") or data.get("PCD_PAYER_NAME") or "카드"
    num = (data.get("PCD_PAY_CARDNUM") or "").replace("*", "").replace("-", "")
    last4 = num[-4:] if len(num) >= 4 else num
    return f"{name} ****{last4}".strip() if last4 else str(name)
