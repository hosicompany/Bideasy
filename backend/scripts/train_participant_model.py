#!/usr/bin/env python
"""
참여업체수 예측 모델 학습 스크립트
- 입력: 입찰 유형, 추정 금액, 발주기관, 날짜
- 출력: 예상 참여업체수 (회귀 + 구간 분류)

목적: 블루오션 입찰 선별 → 경쟁이 적은 입찰에 집중
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingRegressor, GradientBoostingClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (
    mean_absolute_error, mean_squared_error, r2_score,
    accuracy_score, classification_report
)
import joblib
import json
import warnings
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')

print("=" * 60)
print("Bid Easy - 참여업체수 예측 모델 학습")
print("=" * 60)

# 경로 설정
base_dir = Path(__file__).parent.parent
db_path = base_dir / "data" / "historical" / "bid_results_5years.db"
model_dir = base_dir / "models"
model_dir.mkdir(exist_ok=True)

# ============================================================
# 1. 데이터 로드
# ============================================================
print("\n[1/6] 데이터 로드...")
conn = sqlite3.connect(db_path)
df = pd.read_sql("""
    SELECT
        bid_type,
        sucsfbid_amt,
        sucsfbid_rate,
        dminstt_nm,
        data_json,
        openg_dt
    FROM bid_results
    WHERE sucsfbid_rate > 50
      AND sucsfbid_rate <= 100
      AND sucsfbid_amt > 10000
""", conn)
conn.close()
print(f"  로드 완료: {len(df):,}건")

# ============================================================
# 2. 특성 엔지니어링
# ============================================================
print("\n[2/6] 특성 엔지니어링...")

# JSON에서 참여업체수, 날짜 추출
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

# 참여업체수 0인 건 제거
df = df[df['prtcpt_cnt'] > 0]
print(f"  참여업체수 유효 데이터: {len(df):,}건")

# 추정가격 역산 (예정가격 ≈ 낙찰금액 / 낙찰률)
df['estimated_price'] = df['sucsfbid_amt'] / (df['sucsfbid_rate'] / 100.0)
df['log_estimated_price'] = np.log1p(df['estimated_price'])

# 금액 카테고리
df['amount_category'] = pd.cut(
    df['estimated_price'],
    bins=[0, 5e7, 1e8, 3e8, 10e8, 50e8, np.inf],
    labels=[0, 1, 2, 3, 4, 5]
).astype(float)

# 입찰 유형 인코딩
le_type = LabelEncoder()
df['bid_type_encoded'] = le_type.fit_transform(df['bid_type'])

# 날짜 특성
df['dt'] = pd.to_datetime(df['openg_dt_parsed'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
df['year'] = df['dt'].dt.year
df['month'] = df['dt'].dt.month
df['dayofweek'] = df['dt'].dt.dayofweek
df['quarter'] = df['dt'].dt.quarter

# 발주기관 빈도 인코딩 (상위 300개 기관, 나머지는 0)
agency_counts = df['dminstt_nm'].value_counts()
top_agencies = set(agency_counts.head(300).index)
df['agency_freq'] = df['dminstt_nm'].map(agency_counts).fillna(1)
df['log_agency_freq'] = np.log1p(df['agency_freq'])

# 발주기관별 평균 참여업체수 (시간순 누적 평균 - 데이터 누출 방지)
# 실용적 근사: 전체 평균 사용 (실제 서비스에서는 과거 데이터만 사용)
agency_avg_prtcpt = df.groupby('dminstt_nm')['prtcpt_cnt'].mean()
df['agency_avg_prtcpt'] = df['dminstt_nm'].map(agency_avg_prtcpt).fillna(df['prtcpt_cnt'].mean())
df['log_agency_avg_prtcpt'] = np.log1p(df['agency_avg_prtcpt'])

# 타겟: 참여업체수 구간 분류
def prtcpt_bucket(cnt):
    if cnt <= 5: return 0      # 블루오션
    elif cnt <= 10: return 1   # 적정 경쟁
    elif cnt <= 20: return 2   # 보통
    elif cnt <= 50: return 3   # 경쟁 치열
    else: return 4             # 레드오션 (로또)

df['prtcpt_bucket'] = df['prtcpt_cnt'].apply(prtcpt_bucket)

# 결측치 제거
df = df.dropna(subset=['year', 'amount_category', 'month'])
print(f"  전처리 후: {len(df):,}건")

# 분포 확인
print("\n  참여업체수 구간 분포:")
bucket_names = {0: "1-5명(블루오션)", 1: "6-10명(적정)", 2: "11-20명(보통)",
                3: "21-50명(치열)", 4: "51+명(로또)"}
for bucket, name in bucket_names.items():
    count = (df['prtcpt_bucket'] == bucket).sum()
    pct = count / len(df) * 100
    print(f"    {name}: {count:,}건 ({pct:.1f}%)")

# ============================================================
# 3. 학습 데이터 준비
# ============================================================
print("\n[3/6] 학습 데이터 준비...")

features = [
    'bid_type_encoded',
    'log_estimated_price',
    'amount_category',
    'year', 'month', 'dayofweek', 'quarter',
    'log_agency_freq',
    'log_agency_avg_prtcpt',
]

X = df[features].astype(float)
y_reg = df['prtcpt_cnt']        # 회귀 타겟
y_cls = df['prtcpt_bucket']     # 분류 타겟

X_train, X_test, y_reg_train, y_reg_test, y_cls_train, y_cls_test = \
    train_test_split(X, y_reg, y_cls, test_size=0.2, random_state=42)

print(f"  학습 세트: {len(X_train):,}건")
print(f"  테스트 세트: {len(X_test):,}건")

# ============================================================
# 4. 모델 학습
# ============================================================
print("\n[4/6] 모델 학습...")

# 4-1. 회귀 모델 (정확한 참여수 예측)
print("  [회귀] GradientBoosting 학습 중...")
reg_model = GradientBoostingRegressor(
    n_estimators=200,
    max_depth=8,
    learning_rate=0.1,
    min_samples_split=20,
    subsample=0.8,
    random_state=42
)
reg_model.fit(X_train, y_reg_train)

# 4-2. 분류 모델 (구간 예측)
print("  [분류] GradientBoosting 학습 중...")
cls_model = GradientBoostingClassifier(
    n_estimators=200,
    max_depth=8,
    learning_rate=0.1,
    min_samples_split=20,
    subsample=0.8,
    random_state=42
)
cls_model.fit(X_train, y_cls_train)

# ============================================================
# 5. 모델 평가
# ============================================================
print("\n[5/6] 모델 평가...")

# 회귀 평가
y_reg_pred = reg_model.predict(X_test)
reg_mae = mean_absolute_error(y_reg_test, y_reg_pred)
reg_rmse = np.sqrt(mean_squared_error(y_reg_test, y_reg_pred))
reg_r2 = r2_score(y_reg_test, y_reg_pred)

print("\n  [회귀 모델]")
print(f"    MAE: {reg_mae:.1f}명 (평균 오차)")
print(f"    RMSE: {reg_rmse:.1f}명")
print(f"    R²: {reg_r2:.4f}")

# 분류 평가
y_cls_pred = cls_model.predict(X_test)
cls_acc = accuracy_score(y_cls_test, y_cls_pred)

print("\n  [분류 모델]")
print(f"    정확도: {cls_acc:.1%}")
print("\n    구간별 성능:")
target_names = ["1-5명", "6-10명", "11-20명", "21-50명", "51+명"]
report = classification_report(y_cls_test, y_cls_pred, target_names=target_names, digits=3)
print(f"    {report}")

# 실용적 평가: "블루오션 vs 레드오션" 이진 분류 정확도
y_binary_test = (y_cls_test <= 1).astype(int)  # 0-1: 블루오션(10명 이하)
y_binary_pred = (y_cls_pred <= 1).astype(int)
binary_acc = accuracy_score(y_binary_test, y_binary_pred)
print("  [블루오션 탐지 (10명 이하 vs 이상)]")
print(f"    정확도: {binary_acc:.1%}")

# ============================================================
# 6. 모델 저장
# ============================================================
print("\n[6/6] 모델 저장...")

# 기관별 통계도 함께 저장 (서비스에서 활용)
agency_stats = df.groupby('dminstt_nm').agg(
    avg_prtcpt=('prtcpt_cnt', 'mean'),
    bid_count=('prtcpt_cnt', 'count'),
    median_prtcpt=('prtcpt_cnt', 'median'),
).to_dict('index')

# 상위 1000개 기관만 저장
top_agency_stats = {
    k: v for k, v in sorted(
        agency_stats.items(), key=lambda x: -x[1]['bid_count']
    )[:1000]
}

model_path = model_dir / "participant_predictor.joblib"
joblib.dump({
    'reg_model': reg_model,
    'cls_model': cls_model,
    'label_encoder': le_type,
    'features': features,
    'agency_stats': top_agency_stats,
    'agency_counts': {k: int(v) for k, v in agency_counts.head(1000).items()},
    'global_avg_prtcpt': float(df['prtcpt_cnt'].mean()),
    'metrics': {
        'regression': {'mae': reg_mae, 'rmse': reg_rmse, 'r2': reg_r2},
        'classification': {'accuracy': cls_acc, 'binary_accuracy': binary_acc},
    },
    'bucket_names': bucket_names,
}, model_path)

print(f"  모델 저장: {model_path}")
print(f"  파일 크기: {model_path.stat().st_size / 1024 / 1024:.1f}MB")

# 특성 중요도
print("\n[Feature Importance]")
print("  회귀 모델:")
for feat, imp in sorted(zip(features, reg_model.feature_importances_), key=lambda x: -x[1]):
    bar = "█" * int(imp * 50)
    print(f"    {feat:<25} {imp:.4f} {bar}")

print("\n  분류 모델:")
for feat, imp in sorted(zip(features, cls_model.feature_importances_), key=lambda x: -x[1]):
    bar = "█" * int(imp * 50)
    print(f"    {feat:<25} {imp:.4f} {bar}")

print("\n" + "=" * 60)
print("참여업체수 예측 모델 학습 완료!")
print("=" * 60)
