# 비밀키 로테이션 런북

> 작성 2026-08-01. 대상: 운영 중인 BidEasy 백엔드(Lightsail + Docker Compose).
> 이 문서는 **"어떻게 바꾸는가"**만 다룹니다. 무엇을 바꿔야 하는지의 현재 상태는 `CLAUDE.md` §1 대기 항목.

---

## 0. 결론 먼저

- 로테이션은 **새 것 발급 → 교체 → 동작 검증 → 구 것 폐기** 순서다. 구 것을 먼저 지우면 그 사이 서비스가 멈춘다.
- **`BILLING_ENC_KEY` 는 로테이션 대상이 아니다** — 바꾸는 순간 고객 빌링키 전부 복호화 불가(§4).
- 위험도 순서: **AWS 루트 키 > Postgres 비번 > OpenAI 키**. 앞의 둘은 사고 시 복구 비용이 크다.
- `.env.production` 편집은 **SSH 직접 접속**이 필요하다. GitHub Actions 배포 버튼은 `deploy|indexnow-backfill|status|health` 만 허용하는 forced command 라 env 를 못 만진다(그게 설계 의도다 — `docs/DEPLOY_CD.md`).

---

## 1. 대상과 위험도

| 키 | 위험도 | 다운타임 | 비고 |
|---|---|---|---|
| **AWS 루트 액세스 키** | 🔴 유출 시 계정 전체 장악 | 없음 | 폐기만 하면 됨(대체 불필요 — 서버는 발송 전용 IAM 사용) |
| **`POSTGRES_PASSWORD`** | 🔴 절차 틀리면 앱이 DB 접속 불가 | **수십 초** | DB 안에서 먼저 바꿔야 한다(§3-2 함정) |
| **`OPENAI_API_KEY`** | 🟠 유출 시 과금 | 없음 | 실패해도 AI 기능만 멈춤 |
| `JWT_SECRET_KEY` | 🟠 바꾸면 **전원 로그아웃** | 없음 | 침해 정황이 있을 때만. 평시 로테이션 대상 아님 |
| `PAYPLE_*` / 토스 키 | 🟠 | 없음 | PG 콘솔에서 재발급 후 교체 |
| `BILLING_ENC_KEY` | ⛔ **변경 금지** | — | §4 |
| IndexNow 키 | ⚪ 비밀 아님 | 없음 | 프로토콜상 `/{key}.txt` 로 공개돼야 정상 |

---

## 2. 공통 준비

```bash
# 서버 접속 (IP 는 Lightsail 콘솔 → 인스턴스에서 확인)
ssh -i ~/.ssh/lightsail_bideasy.pem ubuntu@<서버IP>

cd ~/Bideasy/infra
DC="docker compose -f docker-compose.prod.yml --env-file .env.production -p infra"

# 편집 전 항상 백업 (되돌릴 수 있는 상태를 먼저 만든다)
cp .env.production ~/env.production.bak-$(date +%Y%m%d-%H%M)
```

검증에 쓸 한 줄:
```bash
curl -s https://api.bideasy.kr/health
# {"status":"ok", ..., "database":"connected", "redis":"connected"} 여야 정상
```

---

## 3. 절차

### 3-1. AWS 루트 액세스 키 폐기 🔴

루트 키는 **MFA로도 제한할 수 없는 전권**이다. IAM 사용자 키와 달리 권한 축소가 불가능하므로 존재 자체가 위험이다.

1. AWS 콘솔에 **루트 계정으로** 로그인 → 우측 상단 계정명 → **보안 자격 증명**
2. **액세스 키** 섹션에서 키와 **마지막 사용 시각** 확인
3. 사용처 점검 — 2026-08-01 기준 확인된 바로는 **없다**:
   - 서버 `.env.production` 은 발송 전용 IAM `bideasy-ses-sender` 키를 쓴다 → 무관
   - 개발 PC(`hoseung-thinkpad-x1`)에는 aws CLI 도 `~/.aws/credentials` 의 `[default]` 도 없다 → 무관
   - (구 PC `t14s` 에 `[default]` 사본이 있었다. 그래서 폐기가 필요하다)
4. 불안하면 **비활성화(Deactivate) → 2~3일 관찰 → 삭제**. 마지막 사용 시각이 안 올라가면 안전
5. 같은 화면에서 **루트 계정 MFA** 활성화 여부도 함께 확인

> `~/.aws/credentials` 의 `[bideasy]` 프로필이 루트인지 IAM 인지 불명이면, 콘솔 IAM → 사용자 목록과 대조한다. 정체불명이고 aws CLI 도 없다면 그 파일은 지워도 잃을 게 없다.

### 3-2. `POSTGRES_PASSWORD` 로테이션 🔴

> ⚠️ **가장 흔한 사고**: postgres 이미지는 **최초 init 때만** `POSTGRES_PASSWORD` 로 계정을 만든다.
> `.env.production` 만 고치면 **DB 안의 실제 비밀번호는 그대로**라서, 앱만 접속하지 못하게 되고
> "비번을 바꿨는데 왜 안 되지"로 헤매게 된다. 반드시 **DB 안에서 먼저** 바꾼다.

```bash
# 0) 백업 (필수)
./deploy.sh backup

# 1) DB 안의 비밀번호를 실제로 변경
$DC exec db psql -U bideasy -d bideasy_db -c "ALTER USER bideasy WITH PASSWORD '새비밀번호';"

# 2) 곧바로 .env.production 갱신 — 1~3 사이에는 앱이 DB 에 붙지 못한다
cp .env.production ~/env.production.bak-$(date +%Y%m%d-%H%M)-pg
nano .env.production        # POSTGRES_PASSWORD= 교체

# 3) 앱 계열만 재생성 (db 는 건드리지 않는다)
$DC up -d --force-recreate app celery_worker celery_beat

# 4) 검증
curl -s https://api.bideasy.kr/health
```

**주의**
- 새 비밀번호에 `@ : / # ? &` 를 넣지 말 것 — DB 접속 URL 에 그대로 들어가 파싱이 깨진다. **영문+숫자 24자 이상** 권장
- `bideasy_pass`(기본값)로 두면 **앱이 기동을 거부**한다(`APP_ENV=production` fail-fast, `CLAUDE.md` 함정 #4)
- 1~3 사이에 **수십 초 다운타임**이 생긴다. 트래픽 적은 시간에, 명령을 미리 준비해 연달아 실행
- **복구**: 백업 `.env.production` 을 되돌리고 `ALTER USER` 로 옛 비번을 다시 설정하면 원상복구된다

### 3-3. `OPENAI_API_KEY` 로테이션 🟠

1. platform.openai.com → **API keys** → `Create new secret key`
   (구 키를 먼저 지우면 AI 분석이 즉시 멈춘다 — 새 키가 먼저다)
2. 교체:
   ```bash
   cp .env.production ~/env.production.bak-$(date +%Y%m%d-%H%M)-openai
   nano .env.production        # OPENAI_API_KEY= 교체
   ./deploy.sh deploy
   ```
3. **동작 확인** — 웹에서 공고 하나를 AI 분석. 실패하면 백업본으로 즉시 복구
4. 확인된 뒤 OpenAI 콘솔에서 **구 키 Revoke**

> `OPENAI_API_KEY` 가 없거나 잘못되면 LLM 경로가 전부 실패하고 **규칙기반 팁만** 동작한다(`CLAUDE.md` §13).
> 즉 겉으로는 화면이 뜨므로, 반드시 AI 분석을 실제로 한 번 돌려 확인한다.

### 3-4. 개발 PC 정리

```powershell
# 이관용 임시 SSH 키 백업 파일 (제거한 키가 들어 있다)
Remove-Item 'C:\ProgramData\ssh\administrators_authorized_keys.bak-20260801'
```
지우기 전 원본에 `hermes-mac-to-windows-hosic` 한 줄만 남았는지 확인한다.

**OneDrive 휴지통**: onedrive.live.com → 휴지통 → `_BIDEASY_이관` → 영구 삭제.
평문 API 키가 들어 있으나, §3-1·3-3 을 마치면 그 안의 키들은 이미 무력화된다.

---

## 4. ⛔ 절대 로테이션하면 안 되는 키

**`BILLING_ENC_KEY`** — 고객 빌링키(카드 자동결제 수단)를 Fernet 으로 암호화한 키다.
바꾸거나 잃으면 **기존 빌링키를 전부 복호화할 수 없고**, 고객 전원이 카드를 다시 등록해야 한다.
자동결제는 그때까지 실패한다.

- 위치: 서버 `infra/.env.production` **에만** 존재
- "보안 강화" 명목으로 함께 갈아버리는 사고가 가장 흔하다. 로테이션 스크립트를 만들 때 이 키를 **명시적으로 제외**할 것
- 미설정 시 평문 폴백이므로, 값이 있는 상태를 유지하는 것 자체가 중요하다

`JWT_SECRET_KEY` 도 평시 로테이션 대상이 아니다 — 바꾸면 전 사용자가 로그아웃된다.
침해 정황이 있을 때만 바꾸고, 그때는 사용자 공지와 함께 한다.

---

## 5. 체크리스트

로테이션 1회를 마쳤다면 아래가 모두 참이어야 한다.

- [ ] `curl -s https://api.bideasy.kr/health` → `status:ok` + `database:connected` + `redis:connected`
- [ ] 웹에서 AI 분석 1회 성공 (OpenAI 키를 바꿨다면)
- [ ] 로그인 상태 유지 (JWT 를 건드리지 않았다면 로그아웃이 발생하면 안 된다)
- [ ] `$DC logs --tail 50 app` 에 인증 실패·접속 오류 없음
- [ ] 구 키 폐기 완료 (새 키 검증 **후**)
- [ ] `~/env.production.bak-*` 백업 파일 정리 — 구 비밀키가 서버에 계속 남지 않도록, 검증이 끝나면 지운다
