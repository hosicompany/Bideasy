import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.db.session import get_db
from app.db import models
from app.services.tips_generator import generate_tips
from app.services.scraper import ScraperService

logger = get_logger(__name__)

router = APIRouter()


@router.get("/{bid_no}/analysis")
@limiter.limit("5/day")
async def analyze_bid(
    request: Request,
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
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Get AI Analysis for a specific bid.
    
    환각 방지를 위해 규칙 기반 팁 생성기 사용:
    - 모든 팁은 API 데이터, 법률 기준, 또는 수학적 계산에서 도출
    - LLM 의존성 최소화
    - 초보자를 위한 친절한 설명 포함
    """
    logger.info(f"Enhanced analysis request for bid_no={bid_no}")
    
    # 1. Check Cache
    cached_log = db.query(models.AIAnalysisLog).filter(
        models.AIAnalysisLog.bid_no == bid_no
    ).first()
    
    if cached_log and cached_log.summary_json:
        logger.info(f"Cache hit for {bid_no}")
        # 캐시된 결과가 새 형식인지 확인
        if isinstance(cached_log.summary_json, dict) and "tips" in cached_log.summary_json:
            return cached_log.summary_json
    
    # 2. Collect bid data from query params or DB
    bid_data = {}
    
    # Try to get from DB first
    notice = db.query(models.Notice).filter(models.Notice.bid_no == bid_no).first()
    
    if notice:
        logger.info(f"Using Notice from DB: {notice.title[:50] if notice.title else 'N/A'}...")
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
    
    logger.info(f"Generating tips for: {bid_data.get('title', 'Unknown')[:30]}...")
    
    # 4. Generate tips using rule-based engine (Base Layer)
    try:
        # Fetch User Profile for Personalization
        user = current_user
        user_profile = None
        if user:
            user_profile = {
                "licenses": user.licenses,
                "location": user.location,
                "capacity": user.capacity_cost
            }
        
        analysis_result = generate_tips(bid_data, user_profile)
        
        # 4.1. Qualification Check (Phase 4)
        if user:
            from app.services.qualification_checker import QualificationChecker
            # Prepare Notice Dict (bid_data has most fields, but need consistent keys)
            # BidData keys: title, Organization, LmtRegion?
            # Notice model might be better source if available, but bid_data is what we have blended.
            
            # Map bid_data to keys expected by Checker
            # Checker expects: "LmtRegion" (from region), "bidNtceNm" (from title)
            check_data = {
                "bidNtceNm": bid_data.get("title", ""),
                "LmtRegion": bid_data.get("region", ""),
                "bidNtceNo": bid_no
            }
            
            qual_result = QualificationChecker.check_qualification(check_data, user)
            analysis_result["qualification"] = qual_result
            
            # Add top-level tip for Qualification
            if qual_result["status"] == "FAIL":
                analysis_result["tips"].insert(0, {
                    "category": "eligibility",
                    "icon": "⛔",
                    "title": "입찰 불가: 자격 요건 미달",
                    "content": qual_result["details"][0] if qual_result["details"] else "자격 요건을 확인해주세요.",
                    "source": "자격분석엔진",
                    "importance": "HIGH"
                })
            elif qual_result["status"] == "PASS":
                analysis_result["tips"].insert(0, {
                    "category": "eligibility",
                    "icon": "✅",
                    "title": "입찰 가능: 자격 요건 충족",
                    "content": "지역 및 면허 요건을 만족합니다.",
                    "source": "자격분석엔진",
                    "importance": "LOW" # Positive info doesn't need "High" warning style usually, but good to show.
                })

    except Exception as e:
        logger.error(f"Tips generation error: {e}")
        # Fallback (simplified)
        analysis_result = {"summary": "분석 오류", "tips": []}

    # 4.5. [Phase 2] Enhance with LLM (Summary & Risks)
    # Check if we have content to analyze
    target_content = bid_data.get("content")
    if target_content and len(target_content) > 50:
        from app.services.llm_agent import llm_agent
        logger.info("Calling LLM for deeper analysis...")
        
        try:
            # Synchronous call (or use run_in_executor if needed for async)
            # Since OpenAI call is blocking, we should ideally use async/await or threadpool
            # For MVP, we'll simple-call (FastAPI handles it in threadpool if def is not async, but this is async def)
            # So we must use run_in_executor to avoid blocking the event loop
            
            loop = asyncio.get_event_loop()
            llm_result = await loop.run_in_executor(None, llm_agent.analyze_notice, target_content)
            
            # Merge 1: Summary
            # LLM returns list of 3 strings -> Join them
            llm_summary_lines = llm_result.get("summary_3_lines", [])
            if llm_summary_lines:
                # Replace the simple rule-based summary
                formatted_summary = "\n".join([f"• {line}" for line in llm_summary_lines])
                analysis_result["summary"] = formatted_summary
                logger.info("Replaced summary with LLM result")
            
            # Merge 2: Risks
            # Add as High Priority Tips
            llm_risks = llm_result.get("risk_factors", [])
            for risk in llm_risks:
                analysis_result["tips"].insert(0, {
                    "category": "risk",
                    "icon": "⚠️",
                    "title": f"위험요소: {risk.get('type')}",
                    "content": risk.get('content'),
                    "source": "AI 정밀분석",
                    "importance": risk.get('severity', 'HIGH')
                })
                
        except Exception as e:
            logger.error(f"LLM enhancement failed: {e}")
            # Continue with rule-based result
    
    logger.info(f"Generated {len(analysis_result.get('tips', []))} tips")
    
    # 4.6. Extract A-value and Net Cost if URL is available (Async Scrape)
    target_url = bid_data.get("notice_url") or notice_url
    
    if target_url:
        logger.info(f"Scraping for A-value from {target_url}...")
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
                    logger.info(f"A-value found: {total_a}")
        except Exception as e:
            logger.error(f"Scraping A-value failed: {e}")
    
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
        logger.info(f"Cached analysis for {bid_no}")
    except Exception as e:
        logger.warning(f"Cache save error (non-fatal): {e}")
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
