# BidEasy 15초 영상 프리프로덕션 정본

음성 업로드 전에 확정할 수 있는 A/B 카피, 공고 사례, 장면 시간표, Higgsfield 배경 동선, 캡션과 마스킹 기준을 한곳에 고정한다. 기계 판독 정본은 [`CREATIVE_PREPRODUCTION_15S.json`](./CREATIVE_PREPRODUCTION_15S.json)이다.

## 현재 판정

- 프리비즈: 제작 가능
- Higgsfield 유료 생성: 아직 실행하지 않음
- 최종 영상 queue·게시: 금지
- 남은 필수 입력: 마스킹된 새 전기공사 제품 화면, 대표 실제 음성, 사람 승인

기존 `guide-assets` 다섯 장은 최종 입력으로 사용하지 않는다. 비전기공사 물품 공고, 구형 UI, `안전성 검증`·`예상 투찰가`·`입찰 가능` 표현 또는 사용자 프로필을 포함하기 때문이다. 프리비즈의 회색 제품 영역은 실제 UI가 아니라 교체 위치를 알리는 내부 와이어프레임이다.

## A/B 불변 조건

두 안은 0~2초 헤드라인만 다르다. 2~15초의 배경, 실제 제품 화면, 음성, 비예측 고지, CTA, 엔드라인과 캡션은 같아야 한다.

| 시간 | 화면 | 확정 규칙 |
|---|---|---|
| 0~2초 | A 또는 B 훅 | 유일한 A/B 차이 |
| 2~5초 | 실제 G2B 공고 옆에 현행 BidEasy 패널 등장 | 생성 모델이 UI를 그리지 않음 |
| 5~10초 | 실제 자격·A값·하한선 결과 확대 | 공개 사실과 실제 UI 픽셀만 사용 |
| 10~13초 | `낙찰가는 예측하지 않습니다. 확인 가능한 기준부터 보여드립니다.` | 두 안 동일 |
| 13~15초 | `투찰 전 마지막 확인, BidEasy.` + `이 공고 확인하기` | 민간 서비스 고지 포함 |

## 공고 사례

- 공고번호: `R26BK01488342-000`
- 공고: 하수처리장 전기실 대용량 차단기 설치 공사
- 기관: 대전광역시시설관리공단
- 공고문 기준: A값 447,799원, 전기공사업·대전 지역 요건, 낙찰하한율 89.745%, 제출 후 취소·수정 불가
- 공식 원문: <https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01488342&bidPbancOrd=000&fileSeq=2&fileType=&prcmBsneSeCd=07>

완료 공고라 이해도 테스트와 시연에는 쓸 수 있지만, 행동 테스트 CTA는 시작 직전에 활성 공고로 교체한다.

## 대표 음성 준비표

공유 대본:

> 보고 있는 공고 화면에서 참가자격, A값, 하한선을 확인하세요. 낙찰가는 예측하지 않습니다. 투찰 전 마지막 확인, BidEasy.

- WAV 48kHz 권장
- 12.5~14.8초
- 평소 설명하듯 차분한 한 번 읽기
- 앞뒤 무음 각각 0.2~0.4초
- 배경음악·효과음·TTS 없음

음성은 관리자 전용 입력 업로드를 통해 보관하고 공개 정적 경로에 두지 않는다.

## 로컬 프리비즈 생성

아래 명령은 Higgsfield를 호출하거나 credits를 사용하지 않는다.

```bash
uv run --with-requirements tools/creative_runner/requirements-dev.txt \
  python tools/creative_runner/render_prevoice.py
```

출력은 `tools/creative_runner/preproduction-output/`에 생성된다.

- `higgsfield-storyboard.png`: provider에 전달 가능한 텍스트·UI 없는 배경 동선 보드
- `review-storyboard-A.png`, `review-storyboard-B.png`: 사람 검수 전용 보드
- `copy-layers/A|B/`: 0~2초 훅, 10~13초 비예측 고지, 13~15초 엔드카드의 결정적 PNG
- `silent-previs-A.mp4`, `silent-previs-B.mp4`: 무음 AAC가 든 15초 내부 검수본
- `preproduction-manifest.json`: 해시·규격·게시 금지 상태

모든 사람 검수용 결과에는 `PREVIZ · 실제 UI/음성 교체 전 · 게시 금지`가 표시된다. `higgsfield-storyboard.png`만 provider 입력 후보이며, 나머지는 Higgsfield에 올리지 않는다.

## 최종 입력 캡처 게이트

새 화면은 공개 공고번호·기관·기준일·A값·하한율·공개 자격조건은 남기고 아래를 제거한다.

- G2B 로그인·회사·사업자·인증서·전자문서함
- BidEasy 사용자 회사명·대표자·소재지·면허등록번호·입찰 이력
- 브라우저 프로필·북마크·알림·다른 확장 프로그램
- 담당자 이름·직통전화·이메일·QR
- 낙찰업체·투찰업체명과 사용자별 투찰금액
- 로컬 주소·개발자 도구·API 키·토큰

캡처를 교체한 뒤 `CREATIVE_BRAND_KIT.json`의 source UI 경로·SHA-256을 갱신하고 사람 검수 후에만 brief를 승인·queue한다.
