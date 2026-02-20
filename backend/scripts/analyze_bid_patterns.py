#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sqlite3
import json
import numpy as np
from pathlib import Path
from collections import defaultdict
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

db_path = Path(r"c:\Users\hosic\OneDrive\Coding\MyProject\01_Bid Easy\backend\data\historical\bid_results_5years.db")
conn = sqlite3.connect(str(db_path))

print("=" * 70)
print("낙찰률 개선 가능성 분석")
print("=" * 70)

# 1. 참여업체수별 낙찰률 분포 (하한율 근처 집중도)
print("\n### 1. 참여업체수별 낙찰률 분포 (하한율 근처 집중도)")
for bid_type in ["construction", "goods", "service"]:
    type_name = {"construction": "공사", "goods": "물품", "service": "용역"}[bid_type]
    cursor = conn.execute(f"""
        SELECT sucsfbid_rate, data_json 
        FROM bid_results 
        WHERE bid_type = '{bid_type}' 
        AND sucsfbid_rate > 50 AND sucsfbid_rate <= 100
        AND sucsfbid_amt > 10000
    """)
    
    prtcpt_rates = defaultdict(list)
    for rate, data_json in cursor:
        try:
            data = json.loads(data_json)
            prtcpt = int(data.get("prtcptCnum", 0) or 0)
        except:
            prtcpt = 0
        
        if prtcpt <= 5:
            bucket = "1-5"
        elif prtcpt <= 10:
            bucket = "6-10"
        elif prtcpt <= 20:
            bucket = "11-20"
        elif prtcpt <= 50:
            bucket = "21-50"
        else:
            bucket = "51+"
        prtcpt_rates[bucket].append(rate)
    
    print(f"\n  [{type_name}]")
    print(f"  {'참여수':>6} {'건수':>8} {'평균률':>8} {'표준편차':>8} {'87-89%대':>8} {'89-90%대':>8}")
    for bucket in ["1-5", "6-10", "11-20", "21-50", "51+"]:
        rates = prtcpt_rates[bucket]
        if rates:
            arr = np.array(rates)
            near_lower = np.sum((arr >= 87) & (arr < 89)) / len(arr) * 100
            near_upper = np.sum((arr >= 89) & (arr < 90)) / len(arr) * 100
            print(f"  {bucket:>6} {len(rates):>8,} {np.mean(arr):>8.2f} {np.std(arr):>8.2f} {near_lower:>7.1f}% {near_upper:>7.1f}%")


# 2. 기관별 낙찰률 패턴 (기관마다 다른 패턴이 있는지)
# SQLite does not have STDEV, so compute in Python
print("\n\n### 2. 기관별 낙찰률 패턴 분석")
for bid_type in ["construction", "goods", "service"]:
    type_name = {"construction": "공사", "goods": "물품", "service": "용역"}[bid_type]
    cursor = conn.execute(f"""
        SELECT dminstt_nm, sucsfbid_rate 
        FROM bid_results 
        WHERE bid_type = '{bid_type}' 
        AND sucsfbid_rate > 50 AND sucsfbid_rate <= 100
        AND sucsfbid_amt > 10000
    """)
    
    agency_rates = defaultdict(list)
    for name, rate in cursor:
        agency_rates[name].append(rate)
    
    # Filter agencies with >= 50 records, sort by count desc, take top 20
    filtered = [(name, rates) for name, rates in agency_rates.items() if len(rates) >= 50]
    filtered.sort(key=lambda x: -len(x[1]))
    filtered = filtered[:20]
    
    print(f"\n  [{type_name}] 주요 발주기관 낙찰률 패턴:")
    print(f"  {'기관명':>30} {'건수':>8} {'평균률':>8} {'표준편차':>8}")
    for name, rates in filtered:
        name_str = str(name)[:25] if name else "Unknown"
        arr = np.array(rates)
        print(f"  {name_str:>30} {len(rates):>8,} {np.mean(arr):>8.2f} {np.std(arr):>8.2f}")


# 3. 금액구간별 낙찰률 분산 분석
print("\n\n### 3. 금액구간별 낙찰률 분산 (예측 가능성)")
for bid_type in ["construction", "goods", "service"]:
    type_name = {"construction": "공사", "goods": "물품", "service": "용역"}[bid_type]
    cursor = conn.execute(f"""
        SELECT sucsfbid_amt, sucsfbid_rate
        FROM bid_results 
        WHERE bid_type = '{bid_type}' 
        AND sucsfbid_rate > 50 AND sucsfbid_rate <= 100
        AND sucsfbid_amt > 10000
    """)
    
    amount_rates = defaultdict(list)
    for amt, rate in cursor:
        if amt < 5e7:
            bucket = "5천만 미만"
        elif amt < 1e8:
            bucket = "5천만~1억"
        elif amt < 3e8:
            bucket = "1억~3억"
        elif amt < 10e8:
            bucket = "3억~10억"
        elif amt < 50e8:
            bucket = "10억~50억"
        else:
            bucket = "50억 이상"
        amount_rates[bucket].append(rate)
    
    print(f"\n  [{type_name}]")
    print(f"  {'금액구간':>12} {'건수':>8} {'평균률':>8} {'표준편차':>8} {'최소':>8} {'최대':>8}")
    for bucket in ["5천만 미만", "5천만~1억", "1억~3억", "3억~10억", "10억~50억", "50억 이상"]:
        rates = amount_rates[bucket]
        if rates:
            arr = np.array(rates)
            print(f"  {bucket:>12} {len(rates):>8,} {np.mean(arr):>8.2f} {np.std(arr):>8.2f} {np.min(arr):>8.2f} {np.max(arr):>8.2f}")


# 4. 월별/요일별 패턴
print("\n\n### 4. 월별 낙찰률 패턴")
for bid_type in ["construction"]:
    cursor = conn.execute(f"""
        SELECT data_json, sucsfbid_rate
        FROM bid_results 
        WHERE bid_type = '{bid_type}' 
        AND sucsfbid_rate > 50 AND sucsfbid_rate <= 100
        AND sucsfbid_amt > 10000
    """)
    
    monthly_rates = defaultdict(list)
    for data_json, rate in cursor:
        try:
            data = json.loads(data_json)
            dt_str = data.get("rlOpengDt", "")
            if dt_str:
                month = int(dt_str[5:7])
                monthly_rates[month].append(rate)
        except:
            pass
    
    print("\n  [공사] 월별:")
    print(f"  {'월':>4} {'건수':>8} {'평균률':>8} {'표준편차':>8}")
    for month in range(1, 13):
        rates = monthly_rates[month]
        if rates:
            arr = np.array(rates)
            print(f"  {month:>3}월 {len(rates):>8,} {np.mean(arr):>8.2f} {np.std(arr):>8.2f}")


# 5. 동가(tie) 빈도 분석
print("\n\n### 5. 동가 발생 빈도 분석 (하한율 정확히 맞춘 비율)")
for bid_type in ["construction", "goods", "service"]:
    type_name = {"construction": "공사", "goods": "물품", "service": "용역"}[bid_type]
    
    cursor = conn.execute(f"""
        SELECT sucsfbid_rate, data_json, sucsfbid_amt, openg_dt
        FROM bid_results 
        WHERE bid_type = '{bid_type}' 
        AND sucsfbid_rate > 50 AND sucsfbid_rate <= 100
        AND sucsfbid_amt > 10000
    """)
    
    total = 0
    near_lower = 0
    exact_lower = 0
    
    for rate, data_json, amt, openg_dt in cursor:
        total += 1
        if bid_type == "construction":
            planned = amt / (rate / 100.0)
            if planned >= 10e9:
                ll = 85.495
            elif planned >= 5e9:
                ll = 85.495
            elif planned >= 1e9:
                ll = 86.745
            elif planned >= 3e8:
                ll = 87.745
            else:
                ll = 87.745
        elif bid_type == "goods":
            ll = 84.245
        else:
            ll = 87.745
        
        if abs(rate - ll) < 0.05:
            near_lower += 1
        if abs(rate - ll) < 0.01:
            exact_lower += 1
    
    if total > 0:
        print(f"\n  [{type_name}] 총 {total:,}건")
        print(f"    하한율 ±0.01% 이내: {exact_lower:,}건 ({exact_lower/total*100:.1f}%)")
        print(f"    하한율 ±0.05% 이내: {near_lower:,}건 ({near_lower/total*100:.1f}%)")

conn.close()
print("\n" + "=" * 70)
print("분석 완료!")
