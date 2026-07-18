import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.analytics import log_event
from app.core.security import get_current_user, require_admin
from app.core.cache import _get_redis, cache_key
from app.db.session import get_db
from app.db import models
from app.schemas.subscription import tier_at_least, TIER_PRO_PLUS, get_effective_tier
from app.services.tips_generator import generate_tips
from app.services.scraper import ScraperService

logger = get_logger(__name__)

router = APIRouter()


# tier별 일일 분석 한도 (B 시나리오)
AI_DAILY_LIMIT = {
    "free": 1,
    "pro": 50,
    "pro_plus": None,  # None = 무제한
}

# Redis 미가용(dev/test) 시 폴백용 in-memory 카운터.
# ⚠️ 멀티워커/재시작에 취약하므로 운영에서는 Redis 경로가 1차다.
_user_call_log: dict[int, deque[datetime]] = defaultdict(deque)


def _kst_date() -> str:
    """KST 기준 날짜(YYYYMMDD) — 일일 한도 캘린더 리셋 키."""
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y%m%d")


def _raise_limit(tier: str, limit_per_day: int):
    upgrade_target = "Pro" if tier == "free" else "Pro+"
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"하루 AI 분석 한도({limit_per_day}회)를 초과했어요. "
            f"{upgrade_target}로 업그레이드하면 더 많이 분석 가능합니다."
        ),
    )


def check_ai_rate_limit(user: models.User) -> int:
    """효과 tier(체험 포함)에 따라 일일 AI 분석 호출 한도 적용.

    Redis 기반 일일 카운터(멀티워커·재시작 무관)를 1차로 쓰고, Redis 미가용 시
    in-memory 폴백. Returns: 이번 호출 포함 사용 횟수. Raises: 429 한도 초과.
    """
    # 체험(Trial) 사용자도 Pro 한도를 받도록 효과 tier 사용
    effective_tier = get_effective_tier(user)

    if tier_at_least(effective_tier, TIER_PRO_PLUS):
        return 0

    limit_per_day = AI_DAILY_LIMIT.get(effective_tier, AI_DAILY_LIMIT["free"])
    if limit_per_day is None:
        return 0

    user_id = getattr(user, "id", 0)

    # ── 1차: Redis 카운터 (INCR + 일일 만료) ──
    r = _get_redis()
    if r is not None:
        try:
            key = cache_key("ai_limit", user_id, _kst_date())
            new_count = r.incr(key)
            if new_count == 1:
                r.expire(key, 86400)  # 24h 후 자동 소멸
            if new_count > limit_per_day:
                _raise_limit(effective_tier, limit_per_day)
            return new_count
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"AI rate limit Redis 실패, in-memory 폴백: {e}")

    # ── 폴백: in-memory 롤링 24h ──
    now = datetime.now()
    cutoff = now - timedelta(days=1)
    log = _user_call_log[user_id]
    while log and log[0] < cutoff:
        log.popleft()
    if len(log) >= limit_per_day:
        _raise_limit(effective_tier, limit_per_day)
    log.append(now)
    return len(log)


def _strip_qualification(result: dict) -> dict:
    """캐시용: 사용자별 자격 데이터(qualification + eligibility 팁) 제거.

    AIAnalysisLog 는 bid_no 로만 캐시되므로, 자격 블록을 캐시하면 타인에게
    노출됨 → 캐시 전 반드시 제거하고 매 요청마다 _apply_qualification 재계산.
    """
    if not isinstance(result, dict):
        return result
    out = dict(result)
    out.pop("qualification", None)
    if isinstance(out.get("tips"), list):
        out["tips"] = [t for t in out["tips"] if t.get("category") != "eligibility"]
    return out


def _apply_qualification(result: dict, title: str, region: str, bid_no: str, user) -> dict:
    """현재 사용자 기준 자격 판정을 result 에 주입 (캐시 안 함)."""
    if not user or not isinstance(result, dict):
        return result
    from app.services.qualification_checker import QualificationChecker
    out = _strip_qualification(result)  # 혹시 남아있을 잔재 제거
    qual = QualificationChecker.check_qualification(
        {"bidNtceNm": title or "", "LmtRegion": region or "", "bidNtceNo": bid_no}, user
    )
    out["qualification"] = qual
    tips = list(out.get("tips", []))
    if qual.get("status") == "FAIL":
        # 사유 + 처방(있으면)을 함께 — "왜 안 되는지"에서 "어떻게 하면 되는지"로.
        content = qual["details"][0] if qual.get("details") else "자격 요건을 확인해주세요."
        pres = qual.get("prescriptions") or []
        if pres:
            content = f"{content} → {pres[0].get('action', '')}"
        tips.insert(0, {"category": "eligibility", "icon": "⛔", "title": "입찰 불가: 자격 요건 미달",
                        "content": content, "source": "자격분석엔진", "importance": "HIGH"})
    elif qual.get("status") == "UNKNOWN":
        pres = qual.get("prescriptions") or []
        content = pres[0].get("action") if pres else "프로필에서 소재지·보유 면허를 등록해 주세요."
        tips.insert(0, {"category": "eligibility", "icon": "ℹ️", "title": "자격 판정 불가: 프로필 정보 부족",
                        "content": content, "source": "자격분석엔진", "importance": "MEDIUM"})
    elif qual.get("status") == "PASS":
        tips.insert(0, {"category": "eligibility", "icon": "✅", "title": "입찰 가능: 자격 요건 충족",
                        "content": "지역 및 면허 요건을 만족합니다.", "source": "자격분석엔진", "importance": "LOW"})
    out["tips"] = tips
    return out


@router.get("/{bid_no}/analysis")
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
    log_event("ai_analysis_requested", user_id=current_user.id, bid_no=bid_no)

    # Rate limit (B 시나리오: free 3/일, pro 50/일, pro+ 무제한)
    used_count = check_ai_rate_limit(current_user)
    logger.info(f"AI rate check passed: user={current_user.id} tier={current_user.tier} used_today={used_count}")

    # 1. Check Cache
    cached_log = db.query(models.AIAnalysisLog).filter(
        models.AIAnalysisLog.bid_no == bid_no
    ).first()
    
    if cached_log and cached_log.summary_json:
        logger.info(f"Cache hit for {bid_no}")
        # 캐시된 결과가 새 형식인지 확인
        if isinstance(cached_log.summary_json, dict) and "tips" in cached_log.summary_json:
            # 자격은 사용자별이라 캐시에 두지 않음 → 현재 사용자 기준 재계산 후 주입.
            cnotice = db.query(models.Notice).filter(models.Notice.bid_no == bid_no).first()
            c_title = (title or (cnotice.title if cnotice else "")) or ""
            c_region = (region or (getattr(cnotice, "region", "") if cnotice else "")) or ""
            return _apply_qualification(
                _strip_qualification(cached_log.summary_json), c_title, c_region, bid_no, current_user
            )
    
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
    
    # 4.6. [LAST-RESORT fallback] A값/순공사원가 서버 재스크래핑.
    # 주 경로는 익스텐션 DOM(extractor.ts) → 투찰가 계산 API a_value 주입.
    # OpenAPI 는 A값 미제공(판정 C)이라 여기서 g2b 페이지를 재스크래핑하지만,
    # 차세대 인증 강화 시 로그인월에 막힐 수 있어 보조 수단으로만 사용.
    target_url = bid_data.get("notice_url") or notice_url

    if target_url:
        logger.info(f"[fallback] Scraping for A-value from {target_url}...")
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
    
    # 5. Cache the result — 자격(사용자별) 제거 후 저장 (타인 노출 방지)
    cacheable = _strip_qualification(analysis_result)
    try:
        if cached_log:
            # Update existing
            cached_log.summary_json = cacheable
            cached_log.created_at = datetime.utcnow()
        else:
            # Create new
            new_log = models.AIAnalysisLog(
                bid_no=bid_no,
                summary_json=cacheable,
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

    # 응답엔 현재 사용자 자격 포함 (analysis_result 는 이미 inline 블록에서 주입됨)
    return analysis_result


@router.delete("/{bid_no}/analysis/cache")
async def clear_analysis_cache(
    bid_no: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """캐시 삭제 (관리자 전용 — 임의 삭제 시 재분석 비용 유발 방지)"""
    cached = db.query(models.AIAnalysisLog).filter(
        models.AIAnalysisLog.bid_no == bid_no
    ).first()
    
    if cached:
        db.delete(cached)
        db.commit()
        return {"message": f"Cache cleared for {bid_no}"}
    
    return {"message": "No cache found"}
