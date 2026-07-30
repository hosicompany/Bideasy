# 아웃바운드 이메일 (AWS SES) — 설계·운영 런북

> 최종 갱신: 2026-07-30 · 상태: **코드 완성·배포 대기 / 전송은 킬스위치 OFF**
> 상위 맥락: `GROWTH_STRATEGY.md` §C1(전환 병목 = 도달률 0), 동의 층 = `LEAD_ACQUISITION.md` §3-1

---

## 0. 결론 먼저

- **문제**: 체험 만료·마감·추천·리드 육성이 전부 인앱 알림 → 안 들어온 사람에겐 도달률 0.
- **구조**: `동의 게이트 → 발송 어댑터 → 원장`. 발송 경로는 `services/nurture.py` **하나뿐**이고,
  게이트를 우회할 방법을 두지 않았다.
- **현재 상태**: 코드·테스트 완성. `OUTBOUND_EMAIL_ENABLED=False` 라서 실제 전송은 0통이고
  모든 발송은 `dry_run` 으로 원장에만 남는다. **SES 도메인 인증 + 프로덕션 액세스 승인 후** 켠다.

---

## 1. 구성 요소

| 층 | 파일 | 책임 |
|---|---|---|
| 동의 판정 | `services/consent.py` | `can_send_marketing`(단건) / `sendable_filter`(쿼리). 동의·철회·2년 재확인 |
| 오케스트레이션 | `services/nurture.py` | 게이트 → 멱등 선점 → 렌더 → 전송 → 원장. **유일한 발송 진입점** |
| 문구 | `services/email_templates.py` | 템플릿 + 법정 표기 강제("(광고)" 접두·발신자·수신거부) |
| 채널 어댑터 | `services/mailer.py` | MIME 조립 + SES `send_raw_email`. 킬스위치 OFF 면 dry-run |
| 수신거부 | `core/signed_token.py`, `endpoints/unsubscribe.py`, `html/unsubscribe.html` | 무기한 서명 토큰 · GET 조회 / POST 처리 |
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

## 3. 켜는 순서 (외부 리드타임이 먼저다)

### 3-1. AWS 준비 (사람 작업)
1. **도메인 인증**: SES 콘솔 → Verified identities → `bideasy.kr` 도메인 추가 → **DKIM(CNAME 3건)**
   DNS 등록. SPF(`v=spf1 include:amazonses.com ~all`), DMARC(`v=DMARC1; p=none; rua=...`) 권장.
2. **프로덕션 액세스 신청**: 기본은 샌드박스(검증된 주소로만 발송). 신청 시 유스케이스·수신동의
   수집 방식·수신거부 처리 방식을 묻는다 → **`/diagnose` 동의 UI + `/unsubscribe` 원클릭**을 그대로
   기술하면 된다(이미 구현됨).
3. (선택) **Configuration Set** 생성 — 반송·불만(complaint) 이벤트 추적.

### 3-2. 서버 설정 (`infra/.env.production`)
```bash
OUTBOUND_EMAIL_ENABLED=true          # ← 승인 완료 전에는 절대 true 로 두지 않는다
AWS_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=...                # IAM 사용자(ses:SendRawEmail 최소 권한)
AWS_SECRET_ACCESS_KEY=...
SES_FROM_EMAIL=no-reply@bideasy.kr
SES_FROM_NAME=BidEasy
SES_REPLY_TO=support@bideasy.kr
SES_CONFIGURATION_SET=              # 만들었다면 이름
PUBLIC_WEB_URL=https://bideasy.kr
PUBLIC_API_URL=https://api.bideasy.kr
```
그리고 `cd ~/Bideasy/infra && ./deploy.sh deploy` (마이그레이션 자동).

### 3-3. 가동 확인 (순서대로)
```
1) GET  /api/v1/admin/outbound/preview?template=lead_welcome   → 문구·(광고) 표기·수신거부 링크 확인
2) POST /api/v1/admin/outbound/test-send?template=trial_expiry → 거래 템플릿으로 실제 경로 1통
3) GET  /api/v1/admin/outbound                                  → status=sent 확인 (outbound_enabled=true 인지 함께 확인)
4) 받은 메일에서 수신거부 링크 클릭 → /unsubscribe 페이지 → 해지 → /admin/consents 에 withdraw 증적 확인
```
> 광고 템플릿으로 test-send 하면 관리자 본인이 미동의인 한 `skipped/no_consent` 가 나온다. **이게 정상**이며
> 게이트가 살아 있다는 증거다.

---

## 4. 함정·금지

1. **`OUTBOUND_EMAIL_ENABLED` 기본값은 False.** 승인 전에 켜면 샌드박스 거절·미인증 도메인 발송으로
   평판이 깎인다. 평판은 한 번 깎이면 거래 메일까지 안 들어간다.
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

- [ ] **SES 도메인 인증·프로덕션 액세스 신청** (외부 리드타임 — 가장 먼저)
- [ ] 리드 육성 시퀀스: 진단 직후 `lead_welcome` 1통 + 주기 `lead_new_matches` (Celery beat)
- [ ] 체험 라이프사이클 시퀀스 D0/D1/D3/D7/D11/D13 (`GROWTH_STRATEGY.md` §C3) — 광고/거래 구분해 템플릿 배치
- [ ] 반송·불만 웹훅(SNS) 수신 → 자동 suppression (`OutboundMessage` 에 반영)
- [ ] 카카오 알림톡 어댑터(발신프로필·템플릿 심사 후) — 게이트는 그대로 재사용
