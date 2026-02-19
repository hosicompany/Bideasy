#!/usr/bin/env python
"""
낙찰률 예측 모델 학습 스크립트
- 입력: 입찰 정보 (금액, 유형, 기관 등)
- 출력: 예상 낙찰률
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import joblib
import json
import warnings
warnings.filterwarnings('ignore')

print("=" * 60)
print("Bid Easy - Bid Rate Prediction Model Training")
print("=" * 60)

# 경로 설정
base_dir = Path(__file__).parent.parent
db_path = base_dir / "data" / "historical" / "bid_results_5years.db"
model_dir = base_dir / "models"
model_dir.mkdir(exist_ok=True)

# 1. 데이터 로드
print("\n[1/5] Loading data...")
conn = sqlite3.connect(db_path)
df = pd.read_sql("""
    SELECT 
        bid_type,
        sucsfbid_amt,
        sucsfbid_rate,
        dminstt_nm,
        data_json
    FROM bid_results
    WHERE sucsfbid_rate > 0 
      AND sucsfbid_rate <= 100
      AND sucsfbid_amt > 0
    LIMIT 500000
""", conn)
conn.close()
print(f"  Loaded: {len(df):,} records")

# 2. 특성 엔지니어링
print("\n[2/5] Feature engineering...")

# JSON에서 추가 정보 추출
def extract_features(json_str):
    try:
        data = json.loads(json_str)
        return {
            'openg_dt': data.get('rlOpengDt', ''),
            'prtcpt_cnt': int(data.get('prtcptCnum', 0) or 0),
        }
    except:
        return {'openg_dt': '', 'prtcpt_cnt': 0}

# JSON 파싱 (샘플링해서 빠르게)
print("  Extracting from JSON...")
extra_features = df['data_json'].apply(extract_features).apply(pd.Series)
df = pd.concat([df, extra_features], axis=1)

# 날짜 특성
df['openg_dt'] = pd.to_datetime(df['openg_dt'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
df['year'] = df['openg_dt'].dt.year
df['month'] = df['openg_dt'].dt.month
df['dayofweek'] = df['openg_dt'].dt.dayofweek

# 금액 특성
df['log_amount'] = np.log1p(df['sucsfbid_amt'])
df['amount_category'] = pd.cut(df['sucsfbid_amt'], 
                               bins=[0, 1e7, 5e7, 1e8, 5e8, 1e9, np.inf],
                               labels=[0, 1, 2, 3, 4, 5]).astype(float)

# 입찰 유형 인코딩
le_type = LabelEncoder()
df['bid_type_encoded'] = le_type.fit_transform(df['bid_type'])

# 참여업체수 카테고리
df['prtcpt_category'] = pd.cut(df['prtcpt_cnt'],
                               bins=[-1, 2, 5, 10, 20, 50, np.inf],
                               labels=[0, 1, 2, 3, 4, 5]).astype(float)

# 결측치 제거
df = df.dropna(subset=['year', 'amount_category', 'prtcpt_category'])
print(f"  After preprocessing: {len(df):,} records")

if len(df) < 100:
    print("ERROR: Not enough data!")
    exit(1)

# 3. 학습 데이터 준비
print("\n[3/5] Preparing train/test data...")

features = ['bid_type_encoded', 'log_amount', 'amount_category', 
            'year', 'month', 'dayofweek', 'prtcpt_category']

X = df[features].astype(float)
y = df['sucsfbid_rate']

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)
print(f"  Train set: {len(X_train):,} records")
print(f"  Test set: {len(X_test):,} records")

# 4. 모델 학습
print("\n[4/5] Training models...")

# Random Forest
print("  - Training Random Forest...")
rf_model = RandomForestRegressor(
    n_estimators=100,
    max_depth=15,
    min_samples_split=10,
    n_jobs=-1,
    random_state=42
)
rf_model.fit(X_train, y_train)

# Gradient Boosting
print("  - Training Gradient Boosting...")
gb_model = GradientBoostingRegressor(
    n_estimators=100,
    max_depth=8,
    learning_rate=0.1,
    random_state=42
)
gb_model.fit(X_train, y_train)

# 5. 모델 평가
print("\n[5/5] Evaluating models...")

def evaluate_model(model, name, X_test, y_test):
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)
    
    print(f"\n  [{name}]")
    print(f"    MAE: {mae:.2f}% (avg error)")
    print(f"    RMSE: {rmse:.2f}%")
    print(f"    R2: {r2:.4f}")
    
    return {'mae': mae, 'rmse': rmse, 'r2': r2}

rf_metrics = evaluate_model(rf_model, "Random Forest", X_test, y_test)
gb_metrics = evaluate_model(gb_model, "Gradient Boosting", X_test, y_test)

# 최고 모델 선택 및 저장
best_model = rf_model if rf_metrics['mae'] < gb_metrics['mae'] else gb_model
best_name = "Random Forest" if rf_metrics['mae'] < gb_metrics['mae'] else "Gradient Boosting"

print(f"\n  Best Model: {best_name}")

# 모델 저장
model_path = model_dir / "bid_rate_predictor.joblib"
joblib.dump({
    'model': best_model,
    'label_encoder': le_type,
    'features': features,
    'metrics': rf_metrics if best_name == "Random Forest" else gb_metrics
}, model_path)

print(f"\n  Model saved: {model_path}")

# 특성 중요도
print("\n[Feature Importance]")
if hasattr(best_model, 'feature_importances_'):
    importances = best_model.feature_importances_
    for feat, imp in sorted(zip(features, importances), key=lambda x: -x[1]):
        print(f"  - {feat}: {imp:.4f}")

print("\n" + "=" * 60)
print("Model training complete!")
print("=" * 60)
