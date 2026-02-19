# 나라장터 낙찰 데이터 5년치 수집

## 개요
조달청 나라장터 Open API를 통해 5년치(60개월) 낙찰 데이터를 수집합니다.

## 수집 대상
- **물품** (goods)
- **용역** (service)  
- **공사** (construction)

## 파일 구조
```
backend/
├── scripts/
│   ├── collect_5years_data.py   # 메인 수집 스크립트
│   ├── run_collection.bat       # Windows 배치 파일
│   └── run_collection.ps1       # PowerShell 스크립트
└── data/
    └── historical/
        ├── bid_results_5years.db     # SQLite DB (수집 데이터)
        └── collection_state.json     # 수집 상태
```

## 실행 방법

### 1. 기본 실행 (전체 5년치)
```powershell
cd backend
python scripts/collect_5years_data.py
```

### 2. 특정 유형만 수집
```powershell
python scripts/collect_5years_data.py --type goods      # 물품만
python scripts/collect_5years_data.py --type service    # 용역만
python scripts/collect_5years_data.py --type construction  # 공사만
```

### 3. 기간 지정
```powershell
python scripts/collect_5years_data.py --months 12       # 최근 1년
python scripts/collect_5years_data.py --months 24       # 최근 2년
```

### 4. 중단 후 재개
```powershell
python scripts/collect_5years_data.py --resume
```

### 5. 백그라운드 실행 (밤에 돌릴 때)
```powershell
# PowerShell
.\scripts\run_collection.ps1 -Background

# 또는 배치 파일
scripts\run_collection.bat /bg
```

### 6. 진행 상황 모니터링
```powershell
# 실시간 로그 확인
Get-Content data/data_collection.log -Tail 20 -Wait
```

## 저장 형식

### SQLite DB 구조
```sql
-- 낙찰 결과 테이블
bid_results (
    id, bid_ntce_no, bid_ntce_ord, bid_type,
    bid_ntce_nm, dminstt_nm, openg_dt,
    sucsfbid_amt, sucsfbid_rate, sucsfbid_corp_nm,
    presmpt_prce, bsis_amt, rbid_cmplt_yn,
    data_json, collected_at
)

-- 진행 상태 테이블
collection_progress (
    bid_type, period_start, period_end,
    page_no, total_count, collected_count,
    status, updated_at
)
```

### 데이터 조회 예시
```python
import sqlite3

db_path = "data/historical/bid_results_5years.db"
conn = sqlite3.connect(db_path)

# 총 건수 확인
cursor = conn.execute("SELECT COUNT(*) FROM bid_results")
print(f"총 수집: {cursor.fetchone()[0]}건")

# 유형별 건수
cursor = conn.execute("""
    SELECT bid_type, COUNT(*) 
    FROM bid_results 
    GROUP BY bid_type
""")
for row in cursor:
    print(f"{row[0]}: {row[1]}건")
```

## 예상 소요 시간

| 기간 | 예상 건수 | 예상 시간 |
|------|----------|----------|
| 1개월 | ~10,000건 | 5분 |
| 12개월 | ~120,000건 | 1시간 |
| 60개월 (5년) | ~600,000건 | 5-8시간 |

*API 응답 속도에 따라 변동될 수 있음*

## 주의사항

1. **API 키 필요**: `.env` 파일에 `PUBLIC_DATA_KEY` 설정 필요
2. **API 호출 제한**: 0.3초 간격으로 호출 (제한 준수)
3. **디스크 공간**: 5년치 데이터 약 500MB~1GB 예상
4. **네트워크**: 안정적인 인터넷 연결 필요

## 문제 해결

### API 500 에러
- 나라장터 API 서버 상태 확인
- 잠시 후 재시도

### 중단된 경우
```powershell
python scripts/collect_5years_data.py --resume
```

### DB 초기화 (처음부터 다시)
```powershell
Remove-Item data/historical/bid_results_5years.db
python scripts/collect_5years_data.py
```
