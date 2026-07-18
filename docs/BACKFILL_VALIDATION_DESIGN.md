# 5년 전수 개찰결과 백필 + 안전 검증 — 설계

> 목표: "우리 안전 계산(무효·적자 회피)이 더 많은 데이터·연도·카테고리에서도 *일반화*되나"를 검증.
> 승률(사정률 점예측)은 **안 겨냥함**(난수). 시간박스: 아래 산출물 나오면 멈추고 비치헤드로.

## ⚠️ 0. 착수 전 핵심 사실 (설계를 바꿈)
`calculator.py:46 LOWER_LIMIT_RATES` — 카테고리별 낙찰하한율:
- **공사 87.745%** → 무효율(하한선 미달) 깔끔히 정의. **우리 홈.**
- **용역 60.0%** (+"협상계약 등은 다름") → 하한율이 계약유형별로 변동. 검증 복잡.
- **물품 0.0%** → **하한선 없음(최저가).** '무효율' 지표 자체가 없음 = 안전 검증 대상 아님.

**함의:** 물품·급식(eaT, 최저가)엔 우리 '안전' 무기가 구조적으로 안 통함 → **안전 포지션의 비치헤드는 공사 적격심사.** 3종 데이터는 긁되, *검증의 무게중심은 공사*, 용역은 타당성 확인, 물품은 "다른 게임" 확인용.

## 1. 백필 크롤 (서버측)
**확장 대상(재사용):** `app/services/opening_result_crawler.py` — `_fetch_page`, `_parse_item_to_kwargs`, `_upsert_opening_result`. 이미 주 단위 백필하는 `scripts/crawl_opening_results.py` 존재(공사 전용).

**변경점:**
1. **`_fetch_page`에 `bsns_div_cd` 파라미터화** — 현재 `_BSNS_DIV_CONSTRUCTION="3"` 하드코딩. 3종 루프 위해 인자로.
   - 공사 = `"3"` (확인됨). ❓ **용역·물품 bsnsDivCd 코드 확인 필요** (getDataSetOpnStdScsbidInfo 스펙). 후보: 물품 `"1"`, 용역 `"5"` (조달청 통상 코드 — 실행 전 1페이지 probe로 검증).
2. **`OpeningResult`에 `category` 컬럼 추가** (nullable String(20): construction|service|goods) + alembic 마이그레이션. `_parse_item_to_kwargs`가 크롤한 bsnsDivCd→category를 채워 저장. *(현재 category 필드 없어 카테고리 폴드 불가 → 필수)*
3. **신규 스크립트 `scripts/backfill_all_categories.py`**: 2021-01-01~현재, 카테고리 3종 × 주 단위 슬라이딩 × 전 페이지. resumable(연도·카테고리별 체크포인트), rate-limit(페이지 0.3s + 윈도우 3s), 3주마다 중간커밋.

**주의(매핑서 확인):** region 필드는 API 미제공(빈 값) → **지역 폴드 불가**. participants_count도 미제공. 단건조회 불가(날짜범위만).

## 2. 검증 스크립트 `scripts/validate_safety.py`
**재사용:** `autocalibrate/dataset.py:load_records()`(정적+DB 병합), `autocalibrate/optimizer.py:simulate_params(records, adjustment, margin)` → `{win_rate, pass_rate, dropout_rate, dropout_rate_uw}`.

**폴드:** (category × bid_method × bracket × year). 각 폴드에서 **현재 active 전략**(strategy_store.load_active) 파라미터로 `simulate_params` → 무효율(dropout)·통과율.

**산출물 3개 (이거 나오면 멈춤):**
1. **폴드별 무효율/통과율 안정성 표** — 공사에서 연도·bracket 넘어 균일한가(≈95% 통과 유지?). *용역은 하한율 변동 반영해 별도, 물품은 N/A로 표기.*
2. **승률 과적합 정량화** — 연도별 승률 분산(8%→23% 신호)을 수치로 → "승률은 안 판다"를 데이터로 못박음.
   ✅ **실행 완료 (2026-07-17, `docs/BENCHMARK_WIN_REACH.md` §3)** — 결과는 예상과 달랐음: walk-forward 하락폭 +0.6~+2.5%p로 **파라미터 과적합은 미미**, 연도 분산의 주범은 소액수의견적의 2024 레짐 변화(oracle 5.6%→36.8%). 명제 정밀화: "개별 건은 난수(추첨), 분포 수준 전략은 일반화된다."
3. **out-of-sample 테스트** — 2021~2024로 (필요시 재)보정 → 2025 held-out에서 무효율 유지되나. **진짜 일반화 증명.**
4. (부산물) 정직한 마케팅 신뢰신호: **"공사 5년 전수 N만 건 out-of-sample 무효율 X%"** — 벤티 '분석 건수' 대체.

## 3. probe 결과 — 확정 (2026-07-04, 서버 직접 실행)
- **카테고리 코드:** 공사=`3`, 용역=`5`, 물품=`1` (외자=`2` 무시, `4`=없음). 응답 `bsnsDivNm`으로 확인.
- **스키마 3종 동일(38필드)** → `_parse_item_to_kwargs` 그대로 재사용. 분기 불필요.
- **⚠️ API 조회범위 ≤ 24h** → 백필은 **하루 단위 창**(주간 아님). start·end 모두 실제시각(`%Y%m%d%H%M`), 미래 종료시각 금지. (넓으면 "입력범위값 초과 에러".)
- **하한율은 API가 레코드별 제공**(`sucsfLwstlmtRt`) → 하드코딩 불필요. 용역도 이걸로 적용.
- **물품은 `rsrvtnPrce`·하한 빈 값**(최저가) → 안전 무효율 N/A 재확인. 용역은 `rsrvtnPrce` 있음 → 안전 적용 가능.
- **크롤러 정상 동작** 확인(`crawl_recent_openings` inserted/updated>0) → 일일 개찰 크롤 안 깨짐.
- 남은 것: `category` 컬럼 마이그레이션(저장 시 요청 bsnsDivCd→category 매핑).

## 4. 실행 절차 (서버, `PUBLIC_DATA_KEY` 필요)
```
1. alembic 마이그레이션 (category 컬럼)
2. python scripts/backfill_all_categories.py   # 며칠 소요(rate limit)
3. python scripts/validate_safety.py           # 폴드 표 + 과적합 + OOS 산출
4. 산출물 검토 → 멈춤 → 비치헤드 결정
```

## 5. 시간박스 규율
"폴드 안정성 표 + 과적합 수치 + OOS 무효율" 3개 나오면 **끝.** 파라미터 재튜닝(승률↑)으로 새면 실험복 입은 편안함의 덫. 검증이지 최적화가 아님.
