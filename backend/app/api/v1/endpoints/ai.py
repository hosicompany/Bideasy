import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db import models
from app.services.tips_generator import generate_tips
from app.services.scraper import ScraperService

router = APIRouter()


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
    contract_type: Optional[str] = Query(None),
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
    Get AI Analysis for a specific bid.
    
    환각 방지를 위해 규칙 기반 팁 생성기 사용:
    - 모든 팁은 API 데이터, 법률 기준, 또는 수학적 계산에서 도출
    - LLM 의존성 최소화
    - 초보자를 위한 친절한 설명 포함
    """
    print(f"[AI] Enhanced analysis request for bid_no={bid_no}", flush=True)
    
    # 1. Check Cache
    cached_log = db.query(models.AIAnalysisLog).filter(
        models.AIAnalysisLog.bid_no == bid_no
    ).first()
    
    if cached_log and cached_log.summary_json:
        print(f"[AI] Cache hit for {bid_no}", flush=True)
        # 캐시된 결과가 새 형식인지 확인
        if isinstance(cached_log.summary_json, dict) and "tips" in cached_log.summary_json:
            return cached_log.summary_json
    
    # 2. Collect bid data from query params or DB
    bid_data = {}
    
    # Try to get from DB first
    notice = db.query(models.Notice).filter(models.Notice.bid_no == bid_no).first()
    
    if notice:
        print(f"[AI] Using Notice from DB: {notice.title[:50] if notice.title else 'N/A'}...", flush=True)
        try:
            bid_data = notice.to_dict()
        except AttributeError:
            # Fallback
            bid_data = {
                "title": notice.title,
                "basic_price": notice.basic_price,
                "organization": getattr(notice, "organization", None),
                "contract_type": getattr(notice, "contract_type", "CONSTRUCTION"),
            }
    
    # Override/supplement with query params (they are more recent)
    param_data = {
        "title": title,
        "basic_price": basic_price,
        "organization": organization,
        "demand_organization": demand_organization,
        "bid_method": bid_method,
        "contract_method": contract_method,
        "contract_type": contract_type or "CONSTRUCTION",
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
    
    # Merge: query params take precedence if not None
    for key, value in param_data.items():
        if value is not None:
            bid_data[key] = value
    
    # 3. Validate minimum data
    if not bid_data.get("title") and not bid_data.get("basic_price"):
        raise HTTPException(
            status_code=400,
            detail="분석에 필요한 공고 정보가 부족합니다. (제목 또는 기초금액 필요)"
        )
    
    print(f"[AI] Generating tips for: {bid_data.get('title', 'Unknown')[:30]}...", flush=True)
    
    # 4. Generate tips using rule-based engine (NO LLM = NO HALLUCINATION)
    try:
        analysis_result = generate_tips(bid_data)
    except Exception as e:
        print(f"[AI] Tips generation error: {e}", flush=True)
        # Fallback instead of Raising 500
        analysis_result = {
            "summary": f"{bid_data.get('title', '공고')} (분석 데이터 생성 실패)",
            "tips": [{
                "category": "system",
                "icon": "⚠️",
                "title": "분석 실패",
                "content": "공고 상세 정보를 분석하는 중 오류가 발생했습니다. 아래 [공고 원문 보기]를 통해 상세 내용을 확인해주세요.",
                "importance": "HIGH",
                "source": "System Fallback"
            }],
            "eligibility": {"can_participate": None, "source": "Fallback"},
            "deadline_info": {"source": "Fallback"},
            "price_info": {"error": "분석 실패"},
            "meta": {
                "generated_at": datetime.utcnow().isoformat(),
                "error": str(e),
                "data_source": "Fallback"
            }
        }
    
    print(f"[AI] Generated {len(analysis_result.get('tips', []))} tips", flush=True)
    
    # 4.5. Extract A-value and Net Cost if URL is available (Async Scrape)
    target_url = bid_data.get("notice_url") or notice_url
    
    if target_url:
        print(f"[AI] Scraping for A-value from {target_url}...", flush=True)
        try:
            loop = asyncio.get_event_loop()
            # Run blocking scrape in thread pool
            content = await loop.run_in_executor(None, ScraperService.fetch_page_content, target_url)
            
            if content:
                a_value_data = ScraperService.extract_a_value(content)
                net_cost = ScraperService.extract_net_cost(content)
                
                # Add to result
                analysis_result["a_value_info"] = a_value_data
                analysis_result["net_cost"] = net_cost
                
                # Update tip if A-value found
                if a_value_data and a_value_data.get("found"):
                    total_a = a_value_data.get("total", 0)
                    # Insert at top
                    analysis_result["tips"].insert(0, {
                        "type": "safety",
                        "text": f"A값(국민연금 등) {total_a:,}원이 자동 추출되었습니다. 투찰 계산 시 이 금액은 낙찰률이 적용되지 않습니다.",
                        "importance": "high"
                    })
                    print(f"[AI] A-value found: {total_a}", flush=True)
        except Exception as e:
            print(f"[AI] Scraping A-value failed: {e}", flush=True)
    
    # 5. Cache the result
    try:
        if cached_log:
            # Update existing
            cached_log.summary_json = analysis_result
            cached_log.created_at = datetime.utcnow()
        else:
            # Create new
            new_log = models.AIAnalysisLog(
                bid_no=bid_no,
                summary_json=analysis_result,
                risk_factors=[],
                llm_model="rule-based-v1",  # No LLM used
                token_usage=0,
                created_at=datetime.utcnow()
            )
            db.add(new_log)
        
        db.commit()
        print(f"[AI] Cached analysis for {bid_no}", flush=True)
    except Exception as e:
        print(f"[AI] Cache save error (non-fatal): {e}", flush=True)
        db.rollback()
    
    return analysis_result


@router.delete("/{bid_no}/analysis/cache")
async def clear_analysis_cache(bid_no: str, db: Session = Depends(get_db)):
    """캐시 삭제 (디버깅용)"""
    cached = db.query(models.AIAnalysisLog).filter(
        models.AIAnalysisLog.bid_no == bid_no
    ).first()
    
    if cached:
        db.delete(cached)
        db.commit()
        return {"message": f"Cache cleared for {bid_no}"}
    
    return {"message": "No cache found"}
