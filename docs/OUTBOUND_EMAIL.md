# 아웃바운드 이메일 (AWS SES) — 설계·운영 런북

> 최종 갱신: 2026-07-30 · 상태: **배포·가동 완료 (전송 ON, 실발송 검증됨)**
> 상위 맥락: `GROWTH_STRATEGY.md` §C1(전환 병목 = 도달률 0), 동의 층 = `LEAD_ACQUISITION.md` §3-1
> 신청 절차(사람 작업)의 1차 기록은 `OUTBOUND_SETUP.md`. 이 문서는 **코드·운영 런북**이다.

---

## 0. 결론 먼저

- **문제**: 체험 만료·마감·추천·리드 육성이 전부 인앱 알림 → 안 들어온 사람에겐 도달률 0.
- **구조**: `동의 게이트 → 발송 어댑터 → 원장`. 발송 경로는 `services/nurture.py` **하나뿐**이고,
  게이트를 우회할 방법을 두지 않았다.
- **현재 상태 (2026-07-30)**: 코드·테스트 완성 + 배포 + **`OUTBOUND_EMAIL_ENABLED=true` 로 가동 중**.
  거래 템플릿 실제 1통 발송 성공(CloudWatch Send 1·Delivery 1·Bounce 0·Complaint 0), 미동의 광고메일은
  `skipped/no_consent` 로 차단됨을 라이브에서 실증.
- **반송·불만 자동 억제**: 구현 완료(SNS 웹훅 → 영구 반송·불만 자동 등록 → 발송 앞단 차단).
- **리드 육성 시퀀스**: 라이브(2026-08-01, 더블 옵트인). 흐름·설계 판단 = `docs/LEAD_ACQUISITION.md` §3-3.
- **수신거부 처리 결과 통지**: 구현 완료(2026-08-01). 정보통신망법 제50조가 요구하는 **법정 고지**라
  보내도 되는 메일이 아니라 **보내야 하는** 메일이다. `POST /unsubscribe` 가 철회를 처리한 뒤
  `unsub_result`(거래 템플릿)를 발송한다. 세 가지가 계약이다:
  ① **광고를 담지 않는다** — 방금 광고를 거부한 사람에게 가는 메일이라, 재동의 유도·할인 문구가
  한 줄만 섞여도 거부 의사를 무시한 광고 발송이 된다(테스트가 문구를 감시한다).
  ② **통지 실패가 해지를 되돌리지 않는다** — 해지가 안 되는 쪽이 훨씬 나쁘고, 곧 스팸 신고가 된다.
  ③ 멱등 키에 **철회 시각(마이크로초)** 을 넣는다 — 재동의 후 재철회 시 두 번째 통지가 '중복'으로
  조용히 막히면 법정 고지가 누락된다.
  ⚠️ 억제 목록에 오른 주소에는 통지도 막힌다(의도된 동작). 원장에 `skipped/suppressed` 로 증적이 남는다.
- **아직 안 한 것**: 체험 라이프사이클 시퀀스, 알림톡 어댑터.

---

## 1. 구성 요소

| 층 | 파일 | 책임 |
|---|---|---|
| 동의 판정 | `services/consent.py` | `can_send_marketing`(단건) / `sendable_filter`(쿼리). 동의·철회·2년 재확인 |
| 오케스트레이션 | `services/nurture.py` | 게이트 → 멱등 선점 → 렌더 → 전송 → 원장. **유일한 발송 진입점** |
| 문구 | `services/email_templates.py` | 템플릿 + 법정 표기 강제("(광고)" 접두·발신자·수신거부) |
| 채널 어댑터 | `services/mailer.py` | MIME 조립 + SES `send_raw_email`. 킬스위치 OFF 면 dry-run |
| 수신거부 | `core/signed_token.py`, `endpoints/unsubscribe.py`, `html/unsubscribe.html` | 무기한 서명 토큰 · GET 조회 / POST 처리 |
| **억제** | `services/suppression.py`, `models.EmailSuppression` (마이그 `c8e5b1f37d94`) | 반송·불만 주소 발송 금지. **광고·거래 공통**으로 가장 먼저 걸린다 |
| **이벤트 수신** | `services/sns_verify.py`, `endpoints/webhooks_ses.py` | SNS 서명·인증서 출처·TopicArn 검증 → 반송/불만 자동 등록 |
| 원장 | `models.OutboundMessage` (마이그 `a9d3f5c17e42`) | 발송·차단 전건 기록, `dedupe_key` 유니크 |
| 운영 창구 | `endpoints/admin/outbound.py` | 원장 조회·집계, 템플릿 미리보기, 본인 계정 테스트 발송 |

### 왜 이렇게 나눴나
- **게이트를 어댑터가 아니라 오케스트레이터에 뒀다** — 나중에 알림톡 어댑터를 붙일 때 동의 규칙을
  다시 구현하면 한쪽만 고쳐지고 사고가 난다.
- **차단된 건도 원장에 남긴다**(`status=skipped`, `reason=no_consent|no_email|duplicate`) — 조용히
  사라지면 게이트가 도는지 알 수 없다.
- **`send_raw_email` 을 쓴다** — SES `SendEmail` 로는 `List-Unsubscribe` 헤더를 넣을 수 없어
  원클릭 수신거부(RFC 8058)를 구현할 수 없다.

---

## 2. 마케팅 vs 거래 — 절대 섞지 않는다

| | marketing | transactional |
|---|---|---|
| 예 | 신규 매칭 공고, 서비스 소식 | 결제·영수증, 체험 만료 고지 |
| 사전 동의 | **필수**(정보통신망법 §50) | 불요 |
| 제목 | `(광고)` 접두 자동 부착 | 접두 없음 |
| 수신거부 | 링크 + `List-Unsubscribe` 헤더 필수 | 붙이지 않음 |
| 함수 | `nurture.send_marketing` | `nurture.send_transactional` |

⚠️ **거래 메일에 광고 문구를 끼워 넣는 순간 그 메일 전체가 광고가 된다.** 체험 만료 안내에
"지금 결제하면 할인" 같은 문구를 넣지 말 것. 템플릿 카테고리와 함수가 어긋나면 `ValueError`.

---

## 3. 가동 현황 (2026-07-30 완료 — 아래는 실제로 설정된 값)

### 3-1. AWS — ✅ 완료
| 항목 | 실제 값 |
|---|---|
| 프로덕션 액세스 | ✅ GRANTED · 50,000통/일 · 14통/초 · `EnforcementStatus: HEALTHY` |
| 도메인 `bideasy.kr` | ✅ Verified · DKIM SUCCESS · SPF·DMARC 등록됨 (DNS 는 카페24 수동 관리) |
| 발송 전용 IAM | ✅ `bideasy-ses-sender` + 인라인 정책 `BideasySesSendOnly` (`ses:SendRawEmail`·`ses:SendEmail`, `aws:RequestedRegion=ap-northeast-2` 조건) |
| 관리용 IAM | `bideasy-ses-admin`(`ses:*`) — **콘솔 작업 전용, 서버에 두지 않는다** |
| Configuration Set | ⬜ 미생성 — 반송·불만 이벤트 추적 붙일 때 만든다 |

> ⚠️ 로컬 `~/.aws/credentials` `[default]` 는 **루트 계정 액세스 키**다. 폐기 대상(CLAUDE.md 대기 항목).

### 3-2. 서버 (`infra/.env.production`) — ✅ 적용됨
실제로 추가한 것은 **3줄뿐**이다. 나머지(`AWS_REGION`·`SES_FROM_EMAIL`·`SES_FROM_NAME`·`SES_REPLY_TO`·
`PUBLIC_WEB_URL`·`PUBLIC_API_URL`)는 `config.py` 기본값이 이미 운영값과 같아 넣지 않았다.
```bash
OUTBOUND_EMAIL_ENABLED=true
AWS_ACCESS_KEY_ID=AKIA…            # bideasy-ses-sender
AWS_SECRET_ACCESS_KEY=…
```
백업: `~/env.production.bak-20260730-outbound`. 값을 바꾼 뒤에는 **배포(컨테이너 재생성)** 를 해야 반영된다.
`.env.production` 편집은 배포 자동화(forced command)로 불가 — SSH 로 직접 하거나 Lightsail 브라우저 SSH 를 쓴다.

### 3-3. 가동 확인 절차 (재검증할 때 그대로 재사용)
```
1) GET  /api/v1/admin/outbound/preview?template=lead_welcome   → 문구·(광고) 표기·수신거부 링크 확인
2) POST /api/v1/admin/outbound/test-send?template=trial_expiry → 거래 템플릿으로 실제 경로 1통
3) GET  /api/v1/admin/outbound                                  → status=sent · outbound_enabled=true 확인
4) 받은 메일의 수신거부 링크 → /unsubscribe → 해지 → /admin/consents 에 withdraw 증적 확인
5) CloudWatch(AWS/SES): Send·Delivery·Bounce·Complaint 확인 — SES 콘솔의 SentLast24Hours 는 반영이 늦다
```
> 광고 템플릿으로 test-send 하면 관리자 본인이 미동의인 한 `skipped/no_consent` 가 나온다. **이게 정상**이며
> 게이트가 살아 있다는 증거다.

**2026-07-30 실측 결과**: 거래 템플릿 `sent`(MessageId 발급, CloudWatch Send 1·Delivery 1·Bounce 0·Complaint 0) ·
미동의 광고 `skipped/no_consent` · 서명 토큰 정상 200 / 1글자 변조 400.

---

## 3-4. 반송·불만 자동 억제 (2026-07-30 추가)

```
SES 발송 → 반송/불만 발생 → SNS 토픽 → POST /api/v1/webhooks/ses
   → 서명·인증서 출처·TopicArn 검증(실패 403)
   → 영구 반송(Permanent) / 불만(complaint) → email_suppressions 등록
   → 이후 모든 발송이 nurture 앞단에서 skipped(reason=suppressed)
```

- **일시 반송(Transient)은 억제하지 않는다** — 사서함 꽉 참·일시 장애까지 영구 차단하면
  정상 고객을 잃는다. 기록만 남긴다.
- **불만(스팸 신고)은 수신거부 의사로 취급** — 억제 + 해당 Lead/User 의 마케팅 동의를
  즉시 철회하고 `consent_records` 에 `source=ses_complaint` 증적을 남긴다.
- **억제는 광고·거래를 가리지 않는다** — 고객 보호가 아니라 **계정 평판 보호**이기 때문이다.
  반송률 5%·불만율 0.1% 초과 시 AWS 가 계정 발송을 정지시키고, 그러면 결제·영수증도 못 나간다.
- **서명 검증이 이 배관의 급소다** — 검증을 빼면 누구나 가짜 반송을 던져 임의 고객을 발송
  금지로 만들 수 있다(조용한 서비스 거부). `SigningCertURL` 은 `sns.<region>.amazonaws.com`
  으로 고정, `SES_SNS_TOPIC_ARN` 을 설정하면 토픽까지 화이트리스트.
- 운영: `GET /admin/outbound/suppressions`(목록·사유별 집계) · `POST`(수동 등록) ·
  `DELETE`(오탐 해제 — **해제해도 수신동의는 복구되지 않는다**).

### AWS 배선 (1회)
```bash
# 1) 토픽 생성 → 2) 우리 웹훅 구독(구독 확인은 서버가 자동 처리) → 3) 도메인 알림 연결
aws sns create-topic --name bideasy-ses-events --region ap-northeast-2
aws sns subscribe --topic-arn <ARN> --protocol https \
  --notification-endpoint https://api.bideasy.kr/api/v1/webhooks/ses --region ap-northeast-2
aws ses set-identity-notification-topic --identity bideasy.kr --notification-type Bounce    --sns-topic <ARN> --region ap-northeast-2
aws ses set-identity-notification-topic --identity bideasy.kr --notification-type Complaint --sns-topic <ARN> --region ap-northeast-2
# 반송·불만은 SNS 로만 받고 이메일 피드백 전달은 끈다(중복 방지)
aws ses set-identity-feedback-forwarding-enabled --identity bideasy.kr --no-forwarding-enabled --region ap-northeast-2
```
그리고 서버 `.env.production` 에 `SES_SNS_TOPIC_ARN=<ARN>` 추가 후 배포.

---

## 4. 함정·금지

1. **`OUTBOUND_EMAIL_ENABLED`** — 코드 기본값은 False(신규 환경 보호), **운영은 현재 true**. 운영에서 이걸
   끄면 모든 발송이 조용히 `dry_run` 이 되어 "보낸 줄 알았는데 안 감" 사고가 난다. 반대로 승인 없는 환경에서
   켜면 미인증 도메인 발송으로 평판이 깎이고, 평판은 한 번 깎이면 거래 메일까지 안 들어간다.
2. **`mailer.send()` 직접 호출 금지.** 반드시 `nurture.send_marketing/send_transactional` 경유
   (게이트·원장 우회 방지).
3. **`dedupe_key` 규칙**: `"{template}:{subject_type}:{id}[:{주기}]"`. 주기성 메일은 날짜·주차를 키에 넣는다
   (예: `lead_new_matches:lead:42:2026-W31`). 키가 없으면 멱등 보장이 없다.
4. **실패는 키를 해제한다** — 재시도 가능. 반면 `skipped` 는 애초에 키를 쓰지 않는다(나중에 동의를
   받으면 보낼 수 있어야 하므로).
5. **수신거부는 GET 으로 처리하지 않는다.** 메일 스캐너의 링크 프리페치로 사용자 의사와 무관하게
   해지되는 사고를 막기 위해 GET=조회, POST=처리로 분리했다.
6. **수신거부 토큰은 만료되지 않는다.** "언제든 철회 가능"이 법 취지이고, 토큰이 노출돼도 할 수 있는
   일은 해지뿐이다(정보 노출 없음).
7. **발송량 램프업**: 승인 직후 대량 발송 금지. 일 수십 통에서 시작해 반송률(<5%)·불만율(<0.1%)을
   보며 늘린다.

---

## 5. 남은 작업 (다음 단계)

- [x] ~~**반송·불만 자동 억제**~~ (2026-07-30 완료 — §3-4)
- [ ] 리드 육성 시퀀스: 진단 직후 `lead_welcome` 1통 + 주기 `lead_new_matches` (Celery beat, `sendable_filter` 대상만)
- [ ] 체험 라이프사이클 시퀀스 D0/D1/D3/D7/D11/D13 (`GROWTH_STRATEGY.md` §C3) — 광고/거래 구분해 템플릿 배치
- [ ] 수신거부 **처리 결과 통지**(정보통신망법) — 현재 즉시 반영은 되나 통지 메일은 미구현
- [ ] Configuration Set 생성(이벤트 추적 붙일 때)
- [x] ~~SES 도메인 인증·프로덕션 액세스 신청~~ (2026-07-30 완료)
- [x] ~~발송 전용 IAM 키 + 서버 설정 + 실발송 검증~~ (2026-07-30 완료)
- [ ] 카카오 알림톡 어댑터(발신프로필·템플릿 심사 후) — 게이트는 그대로 재사용
