#!/usr/bin/env python
"""
나라장터 낙찰 데이터 5년치 수집 스크립트

실행 방법:
  python scripts/collect_5years_data.py

옵션:
  --resume     중단된 지점부터 재개
  --type       특정 유형만 (goods, service, construction)
  --months     수집 개월수 (기본값: 60)

예:
  python scripts/collect_5years_data.py --resume
  python scripts/collect_5years_data.py --type goods --months 12
"""

import asyncio
import json
import logging
import os
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import sqlite3

# 상위 디렉토리 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from app.services.g2b_api_service import G2BApiService

# 로깅 설정
def setup_logging(log_file: str = "data_collection.log"):
    """로깅 설정"""
    log_dir = Path(__file__).parent.parent / "data"
    log_dir.mkdir(exist_ok=True)
    
    log_path = log_dir / log_file
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_path, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


class HistoricalDataCollector:
    """5년치 낙찰 데이터 수집기"""
    
    # 입찰 유형 목록
    BID_TYPES = ["goods", "service", "construction"]
    
    def __init__(self, api_key: str, data_dir: Path):
        self.api_key = api_key
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 상태 파일 경로
        self.state_file = data_dir / "collection_state.json"
        self.db_file = data_dir / "bid_results_5years.db"
        
        self.logger = logging.getLogger(__name__)
        self.service: Optional[G2BApiService] = None
        
        # 통계
        self.stats = {
            "total_collected": 0,
            "goods": 0,
            "service": 0,
            "construction": 0,
            "errors": 0,
            "started_at": None,
            "last_update": None
        }
    
    def _init_db(self):
        """SQLite DB 초기화"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # 낙찰 결과 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bid_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bid_ntce_no TEXT,
                bid_ntce_ord TEXT,
                bid_type TEXT,
                bid_ntce_nm TEXT,
                dminstt_nm TEXT,
                openg_dt TEXT,
                sucsfbid_amt REAL,
                sucsfbid_rate REAL,
                sucsfbid_corp_nm TEXT,
                presmpt_prce REAL,
                bsis_amt REAL,
                rbid_cmplt_yn TEXT,
                data_json TEXT,
                collected_at TEXT,
                UNIQUE(bid_ntce_no, bid_ntce_ord, bid_type)
            )
        """)
        
        # 수집 진행 상태 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collection_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bid_type TEXT,
                period_start TEXT,
                period_end TEXT,
                page_no INTEGER,
                total_count INTEGER,
                collected_count INTEGER,
                status TEXT,
                updated_at TEXT,
                UNIQUE(bid_type, period_start, period_end)
            )
        """)
        
        conn.commit()
        conn.close()
        self.logger.info(f"DB 초기화 완료: {self.db_file}")
    
    def _save_to_db(self, items: List[Dict], bid_type: str):
        """데이터를 DB에 저장"""
        if not items:
            return 0
        
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        saved_count = 0
        for item in items:
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO bid_results 
                    (bid_ntce_no, bid_ntce_ord, bid_type, bid_ntce_nm, dminstt_nm,
                     openg_dt, sucsfbid_amt, sucsfbid_rate, sucsfbid_corp_nm,
                     presmpt_prce, bsis_amt, rbid_cmplt_yn, data_json, collected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.get("bidNtceNo", ""),
                    item.get("bidNtceOrd", "00"),
                    bid_type,
                    item.get("bidNtceNm", ""),
                    item.get("dminsttNm", ""),
                    item.get("opengDt", ""),
                    float(item.get("sucsfbidAmt", 0) or 0),
                    float(item.get("sucsfbidRate", 0) or 0),
                    item.get("sucsfbidCorpNm", ""),
                    float(item.get("presmptPrce", 0) or 0),
                    float(item.get("bsisAmt", 0) or 0),
                    item.get("rbidCmpltYn", ""),
                    json.dumps(item, ensure_ascii=False),
                    datetime.now().isoformat()
                ))
                saved_count += 1
            except Exception as e:
                self.logger.warning(f"DB 저장 오류: {e}")
        
        conn.commit()
        conn.close()
        return saved_count
    
    def _update_progress(self, bid_type: str, start: str, end: str, 
                         page_no: int, total: int, collected: int, status: str):
        """진행 상태 업데이트"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO collection_progress
            (bid_type, period_start, period_end, page_no, total_count, 
             collected_count, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (bid_type, start, end, page_no, total, collected, status, 
              datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def _load_state(self) -> Dict:
        """저장된 상태 로드"""
        if self.state_file.exists():
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def _save_state(self, state: Dict):
        """상태 저장"""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    
    def _get_resume_point(self, bid_type: str) -> Optional[Dict]:
        """재개 지점 확인"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT period_start, period_end, page_no, collected_count
            FROM collection_progress
            WHERE bid_type = ? AND status = 'in_progress'
            ORDER BY updated_at DESC
            LIMIT 1
        """, (bid_type,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "period_start": row[0],
                "period_end": row[1],
                "page_no": row[2],
                "collected_count": row[3]
            }
        return None
    
    async def collect_period(
        self, 
        bid_type: str, 
        start_date: str, 
        end_date: str,
        resume_page: int = 1
    ) -> int:
        """특정 기간의 데이터 수집 (낙찰정보 현황 API 사용)"""
        batch_size = 999  # API 최대값
        page_no = resume_page
        period_total = 0
        
        self.logger.info(f"[{bid_type}] {start_date} ~ {end_date} 수집 시작 (페이지 {page_no}부터)")
        
        while True:
            try:
                # API 호출 (재시도 포함)
                result = None
                for retry in range(3):
                    try:
                        result = await self.service.get_bid_status(
                            bid_type=bid_type,
                            start_date=start_date,
                            end_date=end_date,
                            num_of_rows=batch_size,
                            page_no=page_no
                        )
                        break
                    except Exception as e:
                        if retry < 2:
                            self.logger.warning(f"  재시도 {retry+1}/3: {e}")
                            await asyncio.sleep(2 ** (retry + 1))  # 2, 4, 8초
                        else:
                            raise
                
                if result is None:
                    break
                
                body = result.get("body", {})
                items = body.get("items", [])
                
                if isinstance(items, dict):
                    items = items.get("item", [])
                
                if not items:
                    self._update_progress(bid_type, start_date, end_date, 
                                         page_no, 0, period_total, "completed")
                    break
                
                items = items if isinstance(items, list) else [items]
                
                # DB에 저장
                saved = self._save_to_db(items, bid_type)
                period_total += saved
                self.stats[bid_type] += saved
                self.stats["total_collected"] += saved
                
                # 진행 상태 업데이트
                total_count = int(body.get("totalCount", 0))
                self._update_progress(bid_type, start_date, end_date, 
                                     page_no, total_count, period_total, "in_progress")
                
                self.logger.info(
                    f"  페이지 {page_no}: {saved}건 저장 "
                    f"(이 기간 {period_total}/{total_count}건, 총 {self.stats['total_collected']}건)"
                )
                
                # 다음 페이지 확인
                if page_no * batch_size >= total_count:
                    self._update_progress(bid_type, start_date, end_date, 
                                         page_no, total_count, period_total, "completed")
                    break
                
                page_no += 1
                await asyncio.sleep(0.3)  # API 호출 제한
                
            except Exception as e:
                self.stats["errors"] += 1
                self.logger.error(f"수집 오류 (페이지 {page_no}): {e}")
                # 진행 상태 저장 후 다음 기간으로
                self._update_progress(bid_type, start_date, end_date, 
                                     page_no, 0, period_total, "error")
                await asyncio.sleep(1)
                break
        
        return period_total
    
    async def collect_all(
        self, 
        bid_types: List[str] = None,
        months: int = 60,
        resume: bool = False,
        base_end_date: Optional[str] = None
    ):
        """전체 데이터 수집
        
        Args:
            bid_types: 수집할 입찰 유형 목록
            months: 수집할 개월 수
            resume: 중단 지점부터 재개 여부
            base_end_date: 수집 종료 기준일 (YYYYMMDD)
        """
        if bid_types is None:
            bid_types = self.BID_TYPES
        
        self._init_db()
        self.service = G2BApiService(self.api_key)
        
        self.stats["started_at"] = datetime.now().isoformat()
        self.logger.info(f"=" * 60)
        self.logger.info(f"나라장터 낙찰 데이터 {months}개월치 수집 시작")
        self.logger.info(f"수집 유형: {', '.join(bid_types)}")
        self.logger.info(f"기준 종료일: {base_end_date or '20250207'}")
        self.logger.info(f"저장 위치: {self.db_file}")
        self.logger.info(f"=" * 60)
        
        try:
            for bid_type in bid_types:
                self.logger.info(f"\n{'='*40}")
                self.logger.info(f"[{bid_type.upper()}] 수집 시작")
                self.logger.info(f"{'='*40}")
                
                # 재개 지점 확인
                resume_info = None
                if resume:
                    resume_info = self._get_resume_point(bid_type)
                    if resume_info:
                        self.logger.info(f"재개 지점 발견: {resume_info}")
                
                # 월별로 수집 (최근 -> 과거 순)
                # 기준 종료일 설정 (기본값: 2025-02-07)
                if base_end_date:
                    end_date = datetime.strptime(base_end_date, "%Y%m%d")
                else:
                    end_date = datetime(2025, 2, 7)
                
                for month_idx in range(months):
                    # 해당 월의 시작/끝 계산
                    period_end = end_date - timedelta(days=30 * month_idx)
                    period_start = period_end - timedelta(days=30)
                    
                    start_str = period_start.strftime("%Y%m%d")
                    end_str = period_end.strftime("%Y%m%d")
                    
                    # 재개 모드에서 이미 완료된 기간 스킵
                    if resume_info:
                        if start_str > resume_info.get("period_end", ""):
                            self.logger.info(f"  {start_str}~{end_str}: 이미 완료, 스킵")
                            continue
                        elif start_str == resume_info.get("period_start", ""):
                            # 이 기간에서 재개
                            resume_page = resume_info.get("page_no", 1)
                            await self.collect_period(bid_type, start_str, end_str, resume_page)
                            resume_info = None  # 재개 완료
                            continue
                    
                    await self.collect_period(bid_type, start_str, end_str)
                    
                    # 월간 대기
                    await asyncio.sleep(1)
                
                self.logger.info(f"[{bid_type.upper()}] 완료: {self.stats[bid_type]}건")
            
        finally:
            await self.service.close()
        
        # 최종 통계
        self.stats["last_update"] = datetime.now().isoformat()
        self._save_state(self.stats)
        
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"수집 완료!")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"총 수집: {self.stats['total_collected']}건")
        self.logger.info(f"  - 물품: {self.stats['goods']}건")
        self.logger.info(f"  - 용역: {self.stats['service']}건")
        self.logger.info(f"  - 공사: {self.stats['construction']}건")
        self.logger.info(f"오류: {self.stats['errors']}건")
        self.logger.info(f"저장 위치: {self.db_file}")
        self.logger.info(f"{'='*60}")
        
        return self.stats


async def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="나라장터 낙찰 데이터 수집")
    parser.add_argument("--resume", action="store_true", help="중단된 지점부터 재개")
    parser.add_argument("--type", dest="bid_type", choices=["goods", "service", "construction"],
                       help="특정 유형만 수집")
    parser.add_argument("--months", type=int, default=60, help="수집 개월수 (기본값: 60)")
    parser.add_argument("--end-date", dest="end_date", help="수집 종료 기준일 (YYYYMMDD, 기본값: 20250207)")
    args = parser.parse_args()
    
    # 로깅 설정
    logger = setup_logging()
    
    # 환경 변수 로드
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)
    
    api_key = os.getenv("PUBLIC_DATA_KEY")
    if not api_key:
        logger.error("PUBLIC_DATA_KEY 환경 변수가 설정되지 않았습니다.")
        sys.exit(1)
    
    # 데이터 저장 디렉토리
    data_dir = Path(__file__).parent.parent / "data" / "historical"
    
    # 수집 유형 결정
    bid_types = [args.bid_type] if args.bid_type else None
    
    # 수집 시작
    collector = HistoricalDataCollector(api_key, data_dir)
    stats = await collector.collect_all(
        bid_types=bid_types,
        months=args.months,
        resume=args.resume,
        base_end_date=args.end_date
    )
    
    return stats


if __name__ == "__main__":
    asyncio.run(main())
