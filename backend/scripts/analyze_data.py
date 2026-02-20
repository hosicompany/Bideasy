#!/usr/bin/env python
"""
수집된 낙찰 데이터 품질 분석 스크립트
"""

import sqlite3
import pandas as pd
from pathlib import Path
import sys
import io

# stdout 인코딩 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# DB 경로
db_path = Path(__file__).parent.parent / "data" / "historical" / "bid_results_5years.db"

print("=" * 60)
print("Bid Easy - 5년치 데이터 품질 분석")
print("=" * 60)

# DB 연결
conn = sqlite3.connect(db_path)

# 기본 통계
print("\n### 1. 기본 통계")
df = pd.read_sql("SELECT * FROM bid_results", conn)
print(f"총 레코드 수: {len(df):,}건")
print(f"컬럼 수: {len(df.columns)}개")

# 유형별 통계
print("\n### 2. 유형별 통계")
type_counts = df['bid_type'].value_counts()
for bid_type, count in type_counts.items():
    print(f"  - {bid_type}: {count:,}건")

# 연도별 통계
print("\n### 3. 연도별 통계")
df['year'] = df['openg_dt'].str[:4]
year_counts = df['year'].value_counts().sort_index()
for year, count in year_counts.items():
    if year and len(str(year)) == 4:
        print(f"  - {year}: {count:,}건")

# Null 값 분석
print("\n### 4. Null/빈 값 분석")
null_counts = df.isnull().sum()
for col, count in null_counts.items():
    if count > 0:
        pct = count / len(df) * 100
        print(f"  - {col}: {count:,}건 ({pct:.1f}%)")

# 낙찰금액 통계
print("\n### 5. 낙찰금액 통계")
valid_amounts = df[df['sucsfbid_amt'] > 0]['sucsfbid_amt']
print(f"  - 유효 건수: {len(valid_amounts):,}건")
print(f"  - 평균: {valid_amounts.mean():,.0f}원")
print(f"  - 중앙값: {valid_amounts.median():,.0f}원")
print(f"  - 최소: {valid_amounts.min():,.0f}원")
print(f"  - 최대: {valid_amounts.max():,.0f}원")

# 낙찰률 통계
print("\n### 6. 낙찰률 통계")
valid_rates = df[(df['sucsfbid_rate'] > 0) & (df['sucsfbid_rate'] <= 100)]['sucsfbid_rate']
print(f"  - 유효 건수: {len(valid_rates):,}건")
print(f"  - 평균: {valid_rates.mean():.2f}%")
print(f"  - 중앙값: {valid_rates.median():.2f}%")
print(f"  - 최소: {valid_rates.min():.2f}%")
print(f"  - 최대: {valid_rates.max():.2f}%")

# 낙찰률 분포
print("\n### 7. 낙찰률 분포 (유형별)")
for bid_type in ['goods', 'service', 'construction']:
    type_rates = df[(df['bid_type'] == bid_type) & (df['sucsfbid_rate'] > 0) & (df['sucsfbid_rate'] <= 100)]['sucsfbid_rate']
    if len(type_rates) > 0:
        print(f"  [{bid_type}]")
        print(f"    평균: {type_rates.mean():.2f}%, 중앙값: {type_rates.median():.2f}%")

# 기관 통계
print("\n### 8. 발주기관 통계")
org_counts = df['dminstt_nm'].value_counts()
print(f"  - 총 기관 수: {len(org_counts):,}개")
print("  - 상위 5개 기관:")
for org, count in org_counts.head(5).items():
    org_name = str(org)[:30] if org else "Unknown"
    print(f"    - {org_name}: {count:,}건")

conn.close()

print("\n" + "=" * 60)
print("분석 완료!")
print("=" * 60)
