"""고객 문의 챗봇 — 자체 LLM 응대 + 대화 로깅 + 문의 티켓.

- POST /support/chat   : BidEasy 도메인 지식 기반 GPT 응답 (비로그인 허용). 대화 로깅.
- POST /support/ticket : 자동응답으로 안 되는 문의 접수(티켓 저장).
- GET  /support/tickets: 관리자 문의 조회.

대화 로그(SupportMessage)는 후속 자가학습(질문 군집·FAQ 마이닝)의 데이터 소스.
LLM 재학습은 하지 않고, 지식베이스(이 시스템 프롬프트 → 추후 RAG)를 키우는 방식.
"""
import secrets as _secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db import models
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import get_current_user, get_current_user_optional

router = APIRouter()
logger = get_logger(__name__)

MAX_REPLY_TOKENS = 500
SESSION_DAILY_CAP = 40  # 세션당 1일 질문 상한 (비용·어뷰징 방지). 추후 IP/Redis 강화.

# ── BidEasy 도메인 지식 (지식베이스 v1; 추후 RAG 로 승격) ──────────────
SYSTEM_PROMPT = """당신은 공공입찰 분석 서비스 'BidEasy(비드이지)'의 친절한 고객 상담 챗봇입니다.
아래 지식만으로 한국어로 답하세요. 모르거나 계정별 상세(결제내역·환불·개인정보 등)는
지어내지 말고 "support@bideasy.kr 로 문의해 주세요"라고 안내하세요.

[말투 규칙 — 반드시 지킬 것]
- 항상 정중한 '해요체'로 답해요. 문장은 "~해요 / ~예요 / ~이에요 / ~드려요 / ~하세요 / ~할 수 있어요" 처럼 끝내세요.
- 절대 반말을 쓰지 마세요. ("~해 / ~야 / ~줘 / ~나와 / ~있어 / ~말해" 같은 반말 종결어미 금지)
- 친근하되 고객을 존중하는 말투예요. '사장님'이라고 불러도 좋아요. 3~5문장 이내로 간결하게.
- 올바른 예: "A값은 사후정산 비목의 합계예요. 공사에만 영향을 미쳐요. 더 궁금한 점 있으면 말씀해 주세요."
- 잘못된 예(반말 — 절대 금지): "A값은 합계를 말해. 공사에만 영향 미쳐. 더 궁금하면 말해 줘."

[BidEasy란]
- 나라장터(G2B) 공공입찰을 돕는 데이터 기반 입찰 안전 비서. 크롬 익스텐션 + 웹앱(bideasy.kr).
- 핵심: 투찰가 계산(낙찰하한선·A값), AI 공고 분석(3줄 요약·독소조항 탐지), 자격 자동 매칭, 마감 알림.
- 중요: 무책임한 '낙찰가 예측'은 하지 않아요. 적자 수주를 막는 정밀 계산·분석에 집중합니다.

[요금제]
- Free: 무료. 투찰가 계산기 무제한, 공고 피드·즐겨찾기, 자격 매칭, AI 분석 하루 1회.
- Pro: 월 19,900원 / 연 191,000원(약 20% 할인). AI 분석 일 50회, Deep Analysis(HWP·PDF 첨부), 경쟁 강도 참고치, 투찰가 검증.
- Pro+: 월 39,900원 / 연 383,000원. Pro 전체 + AI 무제한, 기관 프로파일링, 사정률 분포 분석, 안전 투찰 가이드.
- 신규 가입 시 Pro 14일 무료 체험(신용카드 등록 불필요, 만료 시 자동 Free 전환).

[A값]
- 국민연금·건강보험·노인장기요양·산재·고용보험 등 사후정산 비목의 합계.
- 투찰률이 적용되지 않아 따로 분리해 계산해야 정확한 투찰가가 나와요. 공사에만 영향(물품은 해당 없음).
- 공고문/첨부에서 자동 추정하거나 직접 입력할 수 있어요.

[자격 매칭]
- 마이페이지에 회사 정보(상호·면허·지역·시공능력평가액·실적)를 등록하면, 모든 공고에서 참여 가능 여부(적합/부적합)를 자동 판정해요.

[자가보정]
- 매주 새로 쌓이는 개찰 결과를 스스로 학습해 사정률 추천값을 재최적화해요. 회귀 가드가 성능 퇴행을 막아, 쓸수록 정확해집니다.

[결제·해지]
- 토스페이먼츠/페이플 정기결제. 카드 등록 시 첫 결제가 진행되고 매 주기 자동 갱신돼요.
- 해지는 마이페이지에서 가능하고, 해지해도 남은 기간까지는 그대로 이용한 뒤 Free로 전환돼요.

[설치·로그인]
- 크롬 웹스토어에서 'BidEasy'를 설치하면 나라장터 공고 위에 분석 사이드패널이 떠요.
- 로그인은 이메일/비밀번호, 카카오, 네이버를 지원해요. 익스텐션과 웹앱이 같은 계정을 공유합니다.
- 비밀번호는 마이페이지에서 직접 변경할 수 있어요(소셜 로그인 계정은 비밀번호가 없어요)."""


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: Optional[List[dict]] = None  # [{role, content}, ...]


class TicketRequest(BaseModel):
    message: str
    email: Optional[str] = None
    session_id: Optional[str] = None


def _ask_llm(messages: list) -> str:
    if not settings.OPENAI_API_KEY:
        return "지금은 자동 답변을 드리기 어려워요. support@bideasy.kr 로 문의해 주시면 빠르게 도와드릴게요!"
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, temperature=0.3, max_tokens=MAX_REPLY_TOKENS,
        )
        return (resp.choices[0].message.content or "").strip() or \
            "조금 더 자세히 말씀해 주시겠어요? 아니면 support@bideasy.kr 로 문의해 주세요."
    except Exception as e:
        logger.error(f"support chat LLM error: {e}")
        return "답변 생성 중 문제가 생겼어요. 잠시 후 다시 시도하시거나 support@bideasy.kr 로 문의해 주세요."


@router.post("/chat")
def support_chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """고객 챗봇 응답 — 비로그인도 가능. 대화는 로깅(자가학습 데이터)."""
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="메시지를 입력해주세요.")
    msg = msg[:2000]
    session_id = (req.session_id or "").strip()[:64] or _secrets.token_hex(8)
    uid = current_user.id if current_user else None

    # 레이트리밋 (세션당 1일)
    since = datetime.now(timezone.utc) - timedelta(days=1)
    used = (
        db.query(models.SupportMessage)
        .filter(
            models.SupportMessage.session_id == session_id,
            models.SupportMessage.role == "user",
            models.SupportMessage.created_at >= since,
        )
        .count()
    )
    if used >= SESSION_DAILY_CAP:
        return {
            "answer": "오늘 대화를 많이 나눴네요! 더 자세한 상담은 support@bideasy.kr 로 남겨주시면 빠르게 답변드릴게요.",
            "session_id": session_id, "limited": True,
        }

    db.add(models.SupportMessage(session_id=session_id, user_id=uid, role="user", content=msg))
    db.commit()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in (req.history or [])[-6:]:
        r, c = h.get("role"), h.get("content")
        if r in ("user", "assistant") and c:
            messages.append({"role": r, "content": str(c)[:1500]})
    messages.append({"role": "user", "content": msg})

    answer = _ask_llm(messages)

    db.add(models.SupportMessage(session_id=session_id, user_id=uid, role="assistant", content=answer))
    db.commit()
    return {"answer": answer, "session_id": session_id}


@router.post("/ticket")
def support_ticket(
    req: TicketRequest,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """문의 접수 — 챗봇이 못 풀었거나 상담원 연결 요청 시."""
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="문의 내용을 입력해주세요.")
    email = (req.email or (current_user.email if current_user else None) or "").strip() or None
    ticket = models.SupportTicket(
        user_id=current_user.id if current_user else None,
        email=email,
        message=msg[:4000],
        session_id=(req.session_id or "").strip()[:64] or None,
        status="open",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    logger.info(f"support ticket #{ticket.id} from {email or 'anonymous'}")
    return {"ok": True, "ticket_id": ticket.id, "message": "문의가 접수됐어요. 빠르게 확인하고 답변드릴게요!"}


@router.get("/tickets")
def list_tickets(
    status: str = "open",
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """관리자 — 접수된 문의 조회."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    q = db.query(models.SupportTicket)
    if status:
        q = q.filter(models.SupportTicket.status == status)
    rows = q.order_by(desc(models.SupportTicket.created_at)).limit(min(limit, 500)).all()
    return [
        {
            "id": t.id, "email": t.email, "message": t.message,
            "status": t.status, "user_id": t.user_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]
