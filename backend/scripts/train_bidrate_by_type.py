#!/usr/bin/env python
"""
유형별(물품/용역/공사) 낙찰률 예측 모델 학습
- 물품/용역: 분산이 크므로 전용 모델이 효과적
- 공사: 참여수 많으면 하한율 수렴 → 참여수 기반 전략이 더 유효
- 유형별 개별 모델 + 기관별 통계 생성
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import joblib
import json
import warnings
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')

print("=" * 60)
print("Bid Easy - 유형별 낙찰률 예측 모델 학습")
print("=" * 60)

base_dir = Path(__file__).parent.parent
db_path = base_dir / "data" / "historical" / "bid_results_5years.db"
model_dir = base_dir / "models"
model_dir.mkdir(exist_ok=True)

# ============================================================
# 1. 데이터 로드
# ============================================================
print("\n[1/5] 데이터 로드...")
conn = sqlite3.connect(db_path)
df = pd.read_sql("""
    SELECT
        bid_type,
        sucsfbid_amt,
        sucsfbid_rate,
        dminstt_nm,
        data_json
    FROM bid_results
    WHERE sucsfbid_rate > 50
      AND sucsfbid_rate <= 100
      AND sucsfbid_amt > 10000
""", conn)
conn.close()
print(f"  로드 완료: {len(df):,}건")

# ============================================================
# 2. 공통 특성 엔지니어링
# ============================================================
print("\n[2/5] 특성 엔지니어링...")

def extract_features(json_str):
    try:
        data = json.loads(json_str)
        return {
            'prtcpt_cnt': int(data.get('prtcptCnum', 0) or 0),
            'openg_dt_parsed': data.get('rlOpengDt', ''),
        }
    except:
        return {'prtcpt_cnt': 0, 'openg_dt_parsed': ''}

print("  JSON 파싱 중...")
extra = df['data_json'].apply(extract_features).apply(pd.Series)
df = pd.concat([df, extra], axis=1)
df = df[df['prtcpt_cnt'] > 0]

# 추정가격 역산
df['estimated_price'] = df['sucsfbid_amt'] / (df['sucsfbid_rate'] / 100.0)
df['log_estimated_price'] = np.log1p(df['estimated_price'])
df['log_amount'] = np.log1p(df['sucsfbid_amt'])

# 금액 카테고리
df['amount_category'] = pd.cut(
    df['estimated_price'],
    bins=[0, 5e7, 1e8, 3e8, 10e8, 50e8, np.inf],
    labels=[0, 1, 2, 3, 4, 5]
).astype(float)

# 날짜 특성
df['dt'] = pd.to_datetime(df['openg_dt_parsed'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
df['year'] = df['dt'].dt.year
df['month'] = df['dt'].dt.month
df['dayofweek'] = df['dt'].dt.dayofweek

# 참여업체수 특성
df['log_prtcpt'] = np.log1p(df['prtcpt_cnt'])
df['prtcpt_category'] = pd.cut(
    df['prtcpt_cnt'],
    bins=[-1, 5, 10, 20, 50, np.inf],
    labels=[0, 1, 2, 3, 4]
).astype(float)

# 기관 빈도
agency_counts = df['dminstt_nm'].value_counts()
df['log_agency_freq'] = np.log1p(df['dminstt_nm'].map(agency_counts).fillna(1))

# 결측치 제거
df = df.dropna(subset=['year', 'amount_category', 'prtcpt_category'])
print(f"  전처리 후: {len(df):,}건")

# ============================================================
# 3. 유형별 모델 학습
# ============================================================
print("\n[3/5] 유형별 모델 학습...")

features = [
    'log_estimated_price', 'amount_category',
    'year', 'month', 'dayofweek',
    'log_prtcpt', 'prtcpt_category',
    'log_agency_freq',
]

models = {}
metrics_all = {}

for bid_type in ['construction', 'goods', 'service']:
    type_name = {"construction": "공사", "goods": "물품", "service": "용역"}[bid_type]
    type_df = df[df['bid_type'] == bid_type].copy()
    print(f"\n  [{type_name}] {len(type_df):,}건")

    if len(type_df) < 100:
        print("    데이터 부족, 건너뜀")
        continue

    X = type_df[features].astype(float)
    y = type_df['sucsfbid_rate']

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=8,
        learning_rate=0.1,
        min_samples_split=20,
        subsample=0.8,
        random_state=42,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)

    print(f"    MAE: {mae:.2f}%  RMSE: {rmse:.2f}%  R²: {r2:.4f}")

    # 참여수 구간별 성능
    test_prtcpt = type_df.loc[X_test.index, 'prtcpt_cnt']
    for bucket_name, low, high in [("1-5명", 0, 5), ("6-10명", 5, 10), ("11-20명", 10, 20),
                                    ("21-50명", 20, 50), ("51+명", 50, 99999)]:
        mask = (test_prtcpt > low) & (test_prtcpt <= high)
        if mask.sum() > 0:
            bucket_mae = mean_absolute_error(y_test[mask], y_pred[mask])
            print(f"      {bucket_name}: MAE {bucket_mae:.2f}% ({mask.sum():,}건)")

    models[bid_type] = model
    metrics_all[bid_type] = {'mae': mae, 'rmse': rmse, 'r2': r2}

    # 특성 중요도
    print("    특성 중요도:")
    for feat, imp in sorted(zip(features, model.feature_importances_), key=lambda x: -x[1])[:5]:
        print(f"      {feat}: {imp:.4f}")

# ============================================================
# 4. 기관별 통계 생성
# ============================================================
print("\n[4/5] 기관별 통계 생성...")

agency_bid_stats = {}
for bid_type in ['construction', 'goods', 'service']:
    type_df = df[df['bid_type'] == bid_type]
    stats = type_df.groupby('dminstt_nm').agg(
        avg_rate=('sucsfbid_rate', 'mean'),
        median_rate=('sucsfbid_rate', 'median'),
        std_rate=('sucsfbid_rate', 'std'),
        avg_prtcpt=('prtcpt_cnt', 'mean'),
        bid_count=('sucsfbid_rate', 'count'),
    )
    # 10건 이상 기관만
    stats = stats[stats['bid_count'] >= 10]
    agency_bid_stats[bid_type] = stats.to_dict('index')
    print(f"  [{bid_type}] {len(stats):,}개 기관 통계 생성")

# ============================================================
# 5. 모델 저장
# ============================================================
print("\n[5/5] 모델 저장...")

model_path = model_dir / "bidrate_by_type.joblib"
joblib.dump({
    'models': models,
    'features': features,
    'metrics': metrics_all,
    'agency_bid_stats': agency_bid_stats,
}, model_path)

print(f"  모델 저장: {model_path}")
print(f"  파일 크기: {model_path.stat().st_size / 1024 / 1024:.1f}MB")

print("\n" + "=" * 60)
print("유형별 낙찰률 예측 모델 학습 완료!")
print("=" * 60)
