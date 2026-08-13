# 투찰 알고리즘 검증·고도화 AI 감독 프롬프트

아래 프롬프트는 최신 `origin/master`를 기준으로 읽기 전용 감사를 먼저 수행하고, 명시적 승인 뒤에만 격리된 구현 단계로 넘어가는 감독 계약이다.

```xml
<task>
현재 작업공간의 BidEasy 최신 origin/master를 기준으로 투찰가 추천 시스템을
증거 기반으로 감사하고, 검증 가능한 champion–challenger 체계로 고도화하라.

$graph-orchestrator와 $validate-bid-algorithm을 함께 사용하라.
둘 중 하나라도 없으면 누락된 스킬을 알리고 실행을 중단하라.

목표는 그럴듯한 새 공식을 발명하는 것이 아니다.
현재 알고리즘을 반증 가능한 방식으로 검증하고,
동일 공고·동일 정보시점의 증거로 기존 champion과 경쟁 서비스를 이기며,
안전·수익 제약을 통과한 후보만 shadow 단계에 올리는 것이다.

첫 실행은 반드시 읽기 전용 감사로 끝내라.
코드 변경은 사용자가 APPROVE_IMPLEMENTATION을 명시한 뒤 별도 worktree에서만 시작하라.
</task>

<product_contract>
최상위 목적은 회사별 수익 가능한 가격 1순위 및 최종 낙찰 확률의 향상이다.

하한미달, 입찰무효, 적격탈락, 적자수주는 서로 다른 상태와 라벨로 관리하라.
법적·계산 오류는 0건이어야 하며, 하한미달 위험은 champion보다 악화되면 안 된다.

공사·물품·용역을 모두 다루되 하나의 통합 모델로 강제하지 마라.
각 공고를 PRICE_DOMINANT, QUALIFICATION, COMPREHENSIVE,
NEGOTIATION, UNSUPPORTED로 라우팅하고 route별로 독립 평가·승격하라.

사용자 출력은 위험 한도 안의 보수·균형·공격 정책이다.
각 정책에 추천가, 하한미달 확률, 가격 1순위 확률,
최종 낙찰 확률, 기대이익, 신뢰도와 근거 표본을 표시하라.
근거가 부족하거나 확률이 calibration gate를 통과하지 못하면 기권하라.

업체 원가·마진·실제 제출가는 테넌트 계산에만 쓰고,
명시적 opt-in 없이는 중앙 모델 학습에 사용하지 마라.
</product_contract>

<authority_and_safety>
감사 단계에서는 파일, DB, 배포, 외부 계정 상태를 변경하지 마라.

APPROVE_IMPLEMENTATION 이후에만 최신 origin/master 기반 격리 worktree에서
최소 범위의 코드·테스트·실험 변경을 허용한다.

다음은 각각 별도 승인 없이는 금지한다.
- 경쟁사 계정 구매: APPROVE_COMPETITOR_SPEND
- 고객 연락·광고·외부 메시지: APPROVE_EXTERNAL_RESEARCH
- 운영 전략 승격·배포: APPROVE_PROMOTION:{route}:{strategy_version}
- 실제 입찰 제출 또는 사용자를 대신한 의사결정: 항상 금지

승격 작업은 idempotent하고 atomic해야 하며 rollback 경로를 가져야 한다.
</authority_and_safety>

<grounding_rules>
모든 주장을 observed fact, inference, unknown으로 구분하라.
저장소 문서와 실제 코드가 충돌하면 실제 실행 경로를 우선하되 충돌을 보고하라.
운영 배포 상태를 확인하지 못하면 저장소 상태를 운영 사실로 표현하지 마라.

법령·경쟁사·시장 정보는 현재 1차 출처를 확인하고 시점과 URL을 남겨라.
경쟁사의 마케팅 성능 수치를 독립 검증값으로 취급하지 마라.

추천 시점 이후 생성된 데이터는 피처로 사용할 수 없다.
production과 evaluation이 서로 다른 공식을 구현하지 못하게 하라.
</grounding_rules>

<known_hypotheses_to_reproduce>
다음은 사실로 가정하지 말고 재현·반증할 감사 가설이다.

1. weekly autocalibration이 G-B와 사람 승인을 우회해 active 전략을 교체한다.
2. training dataset과 mock/benchmark의 기초금액 품질 필터가 다르다.
3. 후보 생성에 사용한 연도가 holdout 평가에도 포함되어 시간 누수가 있다.
4. 추정가격이 기초금액으로 자동 입력되는 채널이 있다.
5. 웹·확장·Flutter·백테스트의 하한율, 기본 사정률, A값, 반올림 규칙이 다르다.
6. Smart Bid가 bid_method를 잃고 DEFAULT 전략으로 떨어진다.
7. 선택적 ML 503이 규칙 추천 카드 전체를 실패시킨다.
8. recommendation → 사용자 수정/제출 → 개찰 결과의 연결이 없다.
9. arm 행 수를 공고 표본 수로 오인하거나 무효 참가자를 순위에 포함할 위험이 있다.
</known_hypotheses_to_reproduce>

<execution_graph_contract>
작업 전에 실행 그래프 JSON을 만들고 deterministic validator를 통과시켜라.

각 노드는 id, role, independence_group, inputs, outputs, as_of_policy,
allowed_tools, side_effect, timeout, retry_limit, verifier를 가져야 한다.
각 간선은 성공·실패 조건과 다음 노드를 명시해야 한다.

병렬 감사 노드는 DATA_LINEAGE, FORMULA_RUNTIME, RULES_DOMAIN,
USER_COMPETITOR로 둔다.
fan-in은 모든 필수 산출물과 동일 snapshot hash가 없으면 통과시키지 마라.

모든 cycle에는 max_iterations, progress_signal, abort_condition,
success exit와 failure exit를 둬라.
maker와 verifier는 서로 다른 independence_group이어야 한다.

공유 상태에는 experiment_id, code_sha, data_manifest_hash, formula_hash,
as_of_cutoff, route, feature_version, fold_predictions, metrics,
failure_class, gate_decision, approval_id를 보존하라.
</execution_graph_contract>

<evaluation_contract>
평가 단위는 arm row가 아니라 distinct notice다.
같은 notice와 같은 정보 cutoff에서 champion, challenger,
사용자 기존가와 경쟁사 출력을 paired 비교하라.

시간축은 train → validation → sealed_test로 분리하라.
sealed_test는 최종 후보 선택 후 한 번만 열고 이후 튜닝에 재사용하지 마라.

기준선은 다음을 포함한다.
- 현재 active champion
- 실제 제품에서 관측된 기본값과 사용자 기존 제출가
- 법정 안전 계산
- route별 단순 평균·중앙값·계층 기준선

후보군은 단순 모델부터 시작하라.
- 결정론적 규칙 및 코호트 통계
- 계층·부분 풀링 모델
- calibrated tree/boosting
- quantile 또는 conformal interval
- 검증된 후보의 단순 ensemble

관계형 graph feature 또는 GNN은
기관·지역·업체 관계가 temporal holdout과 ablation에서
단순 모델 이상의 추가 신호를 보인 뒤에만 실험하라.

단계별 주 지표는 다음과 같다.
- offline/shadow: 실제 최종 적격 가격 1순위율.
  불가능하면 valid-price reach라고 명시하고 낙찰률이라 부르지 마라.
- 동의 기반 pilot: eligible 참여건당 실현 기여이익과 최종 낙찰.
- hard constraints: 법적·계산 오류 0, 원가·마진 하한 위반 0.
- 보조 지표: rank regret, valid-band hit, Brier/calibration error,
  interval coverage/width, abstention, coverage, 최악 세그먼트.
- winning-price MAPE는 진단용으로만 사용하라.

하한미달 비열화는 route별 paired 결과에서
challenger 비율이 champion 이하이고,
delta(challenger-champion)의 단측 95% CI 상한이 0 이하일 때만 통과한다.

모든 지표에 모집단, 기간, 필터, 제외 수, distinct notice 수,
coverage, 신뢰구간과 최악 세그먼트를 함께 보고하라.

경쟁사 비교는 디마툴즈, KBiD, 비드프로를 대상으로 하되
승인된 계정과 약관 범위 안에서만 수집하라.
동일 공고·동일 정보 cutoff·마감 전 관측시각·원본 artifact hash가
없는 출력은 우월성 비교에서 제외하라.
intersection cohort와 전체 cohort의 abstention 포함 결과를 모두 보고하라.
</evaluation_contract>

<improvement_loop>
각 route와 후보 family에 대해 다음 루프를 최대 3회 수행하라.

가설 하나 설정
→ 기대 효과와 실패 가능성을 사전 기록
→ 변경 하나만 적용
→ validation 평가
→ 독립 verifier 공격
→ DATA, LEAKAGE, FORMULA, BASELINE, MODEL, EVIDENCE 중 실패 분류
→ 해당 노드로만 복귀

두 번 연속 최소 실용효과가 없으면 해당 family를 중단하라.
sealed_test를 연 뒤에는 같은 test를 보고 추가 튜닝하지 마라.
성과가 좋아도 설명할 수 없는 leakage 또는 segmentation regression이 있으면 폐기하라.
</improvement_loop>

<promotion_contract>
다음 순서의 gate를 모두 통과해야 한다.

G0 Truth:
금액 의미·공식·route·반올림이 전 채널에서 일치하고,
확정 기초금액이 없을 때 명시적으로 기권한다.

G-A Data Reach:
기존 사전등록 정의에 따라 유효 결과 도달률 60% 이상이며,
due cohort와 crawler health가 동시에 정상이다.

G-B Route Evidence:
적격심사는 clean distinct notice 400건 이상과 기존 G-B 조건을 유지한다.
다른 route는 결과를 보기 전에 power analysis와 최소 실용효과를
ExperimentManifest에 고정한다.

G-C Challenger:
안전 hard constraint를 모두 지키고,
paired CI 기준으로 champion보다 주 지표가 개선되어야 한다.

G-D Competitor Claim:
'대표 3사보다 우수'라는 문구는 같은 cohort에서 세 서비스 각각에 대해
사전등록 최소 실용효과와 paired 95% CI를 통과하고 coverage가 열등하지 않을 때만 허용한다.
일부만 이기면 이긴 서비스와 route만 정확히 명시한다.

G-E Product:
24개 회사의 실제 과거 투찰과 파일럿 행동에서
route별 최소 3개 회사가 같은 고비용 문제를 재현하고,
추천 적용·수정·재사용·유료 행동이 기록되어야 한다.

어떤 gate도 자동 배포 권한을 부여하지 않는다.
최종 승격에는 route와 strategy_version이 포함된 사람 승인이 필요하다.
</promotion_contract>

<structured_output_contract>
읽기 전용 감사 종료 시 다음 순서로 제출하고 멈춰라.

1. 현재 판정: VERIFIED, NOT_VERIFIED, BLOCKED 중 하나
2. P0 위험과 재현 근거
3. algorithm-to-user 실제 경로 지도
4. 검증된 실행 그래프와 상태 스키마
5. baseline 재현 결과와 정의
6. 데이터·시간 누수 감사
7. route별 실험 계획과 후보군
8. 경쟁사 paired 수집 프로토콜
9. 24사 고객 검증 프로토콜
10. 필요한 코드 변경 계획, 테스트, rollback
11. 해결되지 않은 unknown과 필요한 승인
12. APPROVE_IMPLEMENTATION을 기다리는 명시적 정지 상태

구현 승인 이후에는 각 반복마다 experiment manifest,
변경 diff, 검증 명령, paired 결과, verifier 판정,
gate decision과 residual risk를 남겨라.
</structured_output_contract>

<default_follow_through_policy>
저위험 읽기·검증은 합리적인 기본값으로 계속 진행하라.
정확성, 민감 데이터, 비용, 외부 연락, 배포에 영향을 주는 정보가 없을 때만 멈춰 물어라.
진행 업데이트는 단계 전환이나 blocker가 있을 때만 짧게 제공하라.
</default_follow_through_policy>

<verification_loop>
최종화 전에 모든 주장과 지표가 실제 tool output 또는 버전된 artifact로
역추적되는지 확인하라.
결정론적 검사는 코드로 수행하고, 서술형 판단만 모델에 맡겨라.
첫 번째 문제를 발견한 뒤 retry, stale state, 정정 데이터,
부분 실패, rollback, production/evaluation skew까지 추가로 검사하라.
검증 실패 시 첫 결과를 제출하지 말고 해당 그래프 노드로 되돌아가라.
</verification_loop>
```
