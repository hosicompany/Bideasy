from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db import models
from app.services.llm_agent import llm_agent
from datetime import datetime
from typing import Optional
import json

router = APIRouter()

def generate_comprehensive_context(data: dict) -> str:
    """Generate comprehensive text context from bid data for LLM analysis."""
    sections = []
    
    # 1. Basic Info
    sections.append("=== 공고 기본 정보 ===")
    if data.get("title"):
        sections.append(f"공고명: {data['title']}")
    if data.get("organization"):
        sections.append(f"공고기관: {data['organization']}")
    if data.get("demand_organization"):
        sections.append(f"수요기관: {data['demand_organization']}")
    if data.get("status"):
        sections.append(f"공고상태: {data['status']}")
    
    # 2. Financial Info
    sections.append("\n=== 금액 정보 ===")
    if data.get("basic_price"):
        try:
            price = float(data["basic_price"])
            sections.append(f"기초금액: {price:,.0f}원")
        except:
            pass
    if data.get("budget_amount"):
        try:
            budget = float(data["budget_amount"])
            if budget > 0:
                sections.append(f"배정예산: {budget:,.0f}원")
        except:
            pass
    
    # 3. Bid Method Info
    sections.append("\n=== 입찰 방식 ===")
    if data.get("bid_method"):
        sections.append(f"입찰방법: {data['bid_method']}")
    if data.get("contract_method"):
        sections.append(f"계약방법: {data['contract_method']}")
    if data.get("bid_type"):
        sections.append(f"입찰분류: {data['bid_type']}")
    
    # 4. Participation Restrictions
    sections.append("\n=== 참가 자격 ===")
    if data.get("region"):
        sections.append(f"참가제한지역: {data['region']}")
    if data.get("sme_only") == "Y":
        sections.append("중소기업 제한: 예 (중소기업만 참가 가능)")
    if data.get("big_company_ok") == "Y":
        sections.append("대기업 참여 가능: 예")
    if data.get("joint_contract") == "Y":
        sections.append("공동계약 가능: 예")
    if data.get("international_bid") == "Y":
        sections.append("국제입찰: 예")
    
    # 5. Schedule
    sections.append("\n=== 일정 ===")
    if data.get("start_date"):
        sections.append(f"입찰시작: {data['start_date']}")
    if data.get("end_date"):
        sections.append(f"입찰마감: {data['end_date']}")
    if data.get("opening_date"):
        sections.append(f"개찰일시: {data['opening_date']}")
    
    # 6. Special Notes
    if data.get("emergency_bid") == "Y":
        sections.append("\n⚠️ 긴급공고입니다!")
    if data.get("rebid_yn") == "Y":
        sections.append("\n⚠️ 재입찰 공고입니다!")
    
    # 7. Attachments
    if data.get("attachment_url"):
        sections.append(f"\n📎 첨부파일: {data['attachment_name'] or '공고규격서'}")
        sections.append(f"   URL: {data['attachment_url']}")
    
    return "\n".join(sections)


@router.get("/{bid_no}/analysis")
async def analyze_bid(
    bid_no: str, 
    # Core fields
    title: Optional[str] = Query(None),
    basic_price: Optional[float] = Query(None),
    organization: Optional[str] = Query(None),
    # Extended fields
    demand_organization: Optional[str] = Query(None),
    bid_method: Optional[str] = Query(None),
    contract_method: Optional[str] = Query(None),
    bid_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    budget_amount: Optional[float] = Query(None),
    opening_date: Optional[str] = Query(None),
    international_bid: Optional[str] = Query(None),
    joint_contract: Optional[str] = Query(None),
    sme_only: Optional[str] = Query(None),
    big_company_ok: Optional[str] = Query(None),
    emergency_bid: Optional[str] = Query(None),
    rebid_yn: Optional[str] = Query(None),
    attachment_url: Optional[str] = Query(None),
    attachment_name: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    notice_url: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Get AI Analysis for a specific bid with comprehensive data.
    Accepts extended bid data via query parameters for rich analysis.
    """
    print(f"[AI] Analysis request for bid_no={bid_no}", flush=True)
    
    # 1. Check Cache
    cached_log = db.query(models.AIAnalysisLog).filter(models.AIAnalysisLog.bid_no == bid_no).first()
    if cached_log:
        print(f"[AI] Cache hit for {bid_no}", flush=True)
        return cached_log.summary_json
    
    # 2. Try to get Notice from DB
    notice = db.query(models.Notice).filter(models.Notice.bid_no == bid_no).first()
    
    bid_data = {}
    
    if notice:
        print(f"[AI] Using Notice from DB: {notice.title[:50]}...", flush=True)
        # Use to_dict() to get all extended fields from DB
        try:
            bid_data = notice.to_dict()
        except AttributeError:
            # Fallback for old schema if to_dict missing
            print("[AI] Warning: notice.to_dict() missing, using partial data")
            bid_data = {
                "title": notice.title,
                "basic_price": notice.basic_price,
                "start_date": notice.start_date.isoformat() if notice.start_date else None,
                "end_date": notice.end_date.isoformat() if notice.end_date else None,
            }
    else:
        # Fallback: build from query params
        bid_data = {
            "title": title,
            "basic_price": basic_price,
            "organization": organization,
            "demand_organization": demand_organization,
            "bid_method": bid_method,
            "contract_method": contract_method,
            "bid_type": bid_type,
            "status": status,
            "region": region,
            "budget_amount": budget_amount,
            "opening_date": opening_date,
            "international_bid": international_bid,
            "joint_contract": joint_contract,
            "sme_only": sme_only,
            "big_company_ok": big_company_ok,
            "emergency_bid": emergency_bid,
            "rebid_yn": rebid_yn,
            "attachment_url": attachment_url,
            "attachment_name": attachment_name,
            "start_date": start_date,
            "end_date": end_date,
        }
    
    # 3. Generate comprehensive context
    content_for_analysis = generate_comprehensive_context(bid_data)
    print(f"[AI] Analysis context: {len(content_for_analysis)} chars", flush=True)
    
    if len(content_for_analysis) < 50:
        raise HTTPException(
            status_code=404, 
            detail="분석할 공고 정보가 부족합니다."
        )
    
    # 4. Call LLM
    try:
        analysis_result = llm_agent.analyze_notice(content_for_analysis)
    except Exception as e:
        print(f"[AI] LLM Error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"AI 분석 중 오류 발생: {str(e)}")
    
    # 5. Cache result
    try:
        new_log = models.AIAnalysisLog(
            bid_no=bid_no,
            summary_json=analysis_result,
            risk_factors=[],
            llm_model="gpt-4o-mini",
            token_usage=0, 
            created_at=datetime.utcnow()
        )
        db.add(new_log)
        db.commit()
        print(f"[AI] Cached analysis for {bid_no}", flush=True)
    except Exception as e:
        print(f"[AI] Cache save error (non-fatal): {e}", flush=True)
    
    return analysis_result
