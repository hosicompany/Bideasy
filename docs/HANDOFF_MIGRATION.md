# BidEasy — PC 이관 인수인계서

> **작성 2026-08-01.** 개발 PC(Windows, `C:\Project\`)가 포맷 예정이라 새 PC에서 작업을 이어받기 위한 문서입니다.
> 이관이 끝나면 역할을 다합니다 — 체크리스트(§6)를 통과하면 이 문서는 더 볼 필요 없습니다.
> **작업 맥락의 정본은 언제나 `CLAUDE.md`** 입니다. 이 문서는 "환경을 옮기는 방법"만 다룹니다.

---

---

## ✅ 이관 실행 완료 (2026-08-01, Tailscale 원격 셋업)

**`hoseung-thinkpad-x1` 로의 이관은 이미 끝났습니다.** 아래 §1~§4는 "어떻게 했는가"의 기록이자,
다른 기기에 다시 이관할 때 쓰는 절차서입니다. 새 PC에서 처음 세션을 여는 것이라면 **§5(작업 재개 지점)와 아래 잔여 작업만** 보면 됩니다.

구 PC(`hoseung-thinkpad-t14s`)에서 Tailscale P2P + SSH로 원격 수행한 결과:

| 항목 | 결과 |
|---|---|
| 레포 4개 | ✅ `C:\Project\` 배치 완료. private 2종(`Bideasy-Extension`·`bideasy-agent`)은 gh 토큰 만료로 `git bundle` 전송 후 복원, origin URL은 GitHub으로 재설정됨 |
| 비공개 파일 5종 | ✅ `.env` 2종·`PATENT.md`·체크리스트 2건 배치. `git status` clean = `.gitignore` 정상 |
| Lightsail SSH 키 | ✅ `~/.ssh/lightsail_bideasy.pem` (소유자 읽기 전용으로 권한 제한) |
| 전역 규칙 | ✅ `~/.claude/GLOBAL_RULES_HOSI.md` + 기존 SuperClaude 진입점에 `@GLOBAL_RULES_HOSI.md` import 추가(덮어쓰기 아님, 원본은 `CLAUDE.md.bak-20260801`) |
| Claude 메모리 9개 | ✅ `~/.claude/projects/C--Project-Bideasy/memory/` — SHA256 해시 일치 검증 |
| Python 환경 | ✅ venv(Python 3.12.10) + `requirements.txt` 설치 |
| **검증** | ✅ **`pytest` 508건 전부 통과** (구 PC와 동일) |

### ⏳ 잔여 작업 (사람이 해야 하는 것)

1. **`gh auth login`** — 대상 PC의 GitHub 토큰이 만료 상태(`The token in default is invalid`). push·PR 작업 전에 필요
2. **임시 SSH 키 제거** — 이관용으로 등록한 키를 지운다. 관리자 PowerShell에서:
   `C:\ProgramData\ssh\administrators_authorized_keys` 의 `bideasy-migration-temp-20260801` 줄 삭제
3. **OneDrive `_BIDEASY_이관\` 꾸러미 삭제** — 평문 API 키가 클라우드에 남아 있다
4. **OpenAI 키·`POSTGRES_PASSWORD` 로테이션** (권고) — 2026-06-19 감사 이후 미처리 항목
5. 익스텐션 `security/audit-2026-06-19` 문서 3커밋 머지 여부 판단 (§1.1)

---

## 0. 결론 먼저 — 이관 난이도는 낮습니다

조사 결과 **이 PC에 붙잡혀 있던 자산은 거의 없습니다.** 소스·문서·최근 작업은 전부 GitHub에 있고,
포맷된 PC의 로컬 사본은 오히려 **원격보다 24커밋 뒤처진 구버전**이었습니다(로컬 2026-07-19 ↔ 원격 2026-07-30).

즉 새 PC에서는 **그냥 clone하면 최신**이고, 따로 챙길 것은 아래 **3가지뿐**입니다.

| 챙길 것 | 어디에 | 왜 |
|---|---|---|
| ① OneDrive `_BIDEASY_이관/` 꾸러미 | 클라우드 (준비 완료) | `.gitignore`라 원격에 없음 — `.env` 2종·`PATENT.md`·Claude 메모리 |
| ② `preserve/*` 브랜치 3개 | GitHub (푸시 완료) | 로컬 stash·미커밋이었던 WIP |
| ③ Lightsail SSH `.pem` 키 | `Downloads` 폴더 — **사용자 직접 백업 필요** | 서버 접속 수단 |

---

## 1. 레포 4개 clone

| 레포 | 역할 | 상태 |
|---|---|---|
| **Bideasy** | 백엔드(FastAPI)+웹(nginx 정적)+Flutter — **정본 `CLAUDE.md` 위치** | ✅ 최신 = `origin/master` |
| **Bideasy-Extension** | 크롬 익스텐션 (TypeScript) | ✅ 최신 = `origin/main` — §1.1 참고 |
| **bideasy-agent** | 운영 위임 에이전트 킷 (Phase 1 read-only) | ✅ 깨끗 |
| **bideasy-policy** | 개인정보처리방침·정책 문서 (웹스토어 심사용) | ✅ 깨끗 |

```bash
mkdir -p ~/Project && cd ~/Project && for r in Bideasy Bideasy-Extension bideasy-agent bideasy-policy; do git clone https://github.com/hosicompany/$r.git; done
```

> 경로는 **`C:\Project\` 그대로** 쓰는 것을 권장합니다. Claude Code 메모리·설정이 `C--Project-Bideasy` 키로 저장돼 있어 경로가 바뀌면 프로젝트 히스토리가 새로 시작됩니다.

### 1.1 익스텐션 — `security/audit-2026-06-19` 잔여 3커밋

보안 수정(`58ef1ec` 로그인 브릿지 토큰·baseURL 검증·CSP)과 개인정보방침 정합(`a0c8628`)은
**PR #1로 이미 `main`에 머지 완료**입니다. 걱정하지 않아도 됩니다.

다만 같은 브랜치에 **문서 3커밋이 아직 main에 없습니다**:
```
4be0cf0 docs: AGENTS.md 문구 표준화 반영
bdf6172 docs: AGENTS.md 포인터 추가 — Codex 등 타 도구용 (정본=CLAUDE.md)
43af05c docs: Claude Code 하네스 추가 (CLAUDE.md·검증 훅)
```
→ 새 PC에서 익스텐션 작업을 시작할 때, 이 3건을 main에 머지할지 판단하세요.
(Claude Code 하네스 문서가 여기 있으므로, 익스텐션 레포에서 Claude를 쓸 계획이면 머지하는 편이 낫습니다.)

---

## 2. 🔴 OneDrive 꾸러미에서 비공개 파일 복원

`.gitignore`로 제외돼 **원격에 존재하지 않는** 파일들입니다. 포맷 시 영구 유실되므로 꾸러미를 만들어 뒀습니다.

**위치**: `OneDrive\_BIDEASY_이관\` (안에 `README_먼저읽기.md` 포함)

| 꾸러미 안 경로 | 복원 위치 | 성격 |
|---|---|---|
| `secrets/backend.env` | `Bideasy/backend/.env` | 로컬 개발용 키 (2026-05-12) |
| `secrets/infra.env.production.local` | `Bideasy/infra/.env.production.local` | ⚠️ 운영 키 **구버전 스냅샷**(2026-05-15) — §2.1 |
| `private-docs/PATENT.md` | `Bideasy/backend/app/services/autocalibrate/PATENT.md` | 🔒 내부 IP — **커밋·푸시 절대 금지** |
| `private-docs/MORNING_CHECKLIST.md` | `Bideasy/MORNING_CHECKLIST.md` | 내부 문서 (커밋 금지) |
| `private-docs/OVERNIGHT_REPORT.md` | `Bideasy/OVERNIGHT_REPORT.md` | 내부 문서 (커밋 금지) |
| `claude-context/GLOBAL_CLAUDE.md` | `~/.claude/CLAUDE.md` | 전역 규칙 (모든 프로젝트 공통) |
| `claude-context/memory/*.md` (7개) | `~/.claude/projects/C--Project-Bideasy/memory/` | Claude 메모리 (경쟁사 3사·가격 결정·pytest 함정 등) |

복원 후 `git status`에 위 파일들이 **안 뜨면 정상**입니다(.gitignore 정상 작동).

### 2.1 ⚠️ `.env.production.local`은 운영 정본이 아닙니다

로컬 스냅샷은 2026-05-15자라 아래 키가 **없습니다**:
`BILLING_ENC_KEY` · `PAYPLE_*` · `PAYMENT_PROVIDER` · `CONTENT_LLM_*` · `OUTBOUND_EMAIL_ENABLED`/SES 키

**운영 정본은 서버 `~/Bideasy/infra/.env.production` 에만 존재합니다.** 이 로컬 파일로 서버를 덮어쓰지 마세요.
특히 **`BILLING_ENC_KEY` 변경·재생성 절대 금지** — 고객 빌링키 전부 복호화 불가가 됩니다.

### 2.2 🔑 자동 복사가 차단돼 직접 챙겨야 하는 것

| 항목 | 위치 | 조치 |
|---|---|---|
| **Lightsail SSH 개인키** | `C:\Users\hosic\Downloads\LightsailDefaultKey-ap-northeast-2.pem` | **포맷 전 직접 백업.** 유실 시 AWS Lightsail 콘솔 브라우저 SSH로 접속해 새 공개키 등록 가능(번거로움) |
| GitHub CLI 인증 | Windows 자격증명(keyring) — 이관 불가 | 새 PC에서 `gh auth login` |
| git 사용자 정보 | — | `git config --global user.name hosicompany` / `user.email hosicompany@gmail.com` |

> 💡 포맷하는 김에 **OpenAI 키·`POSTGRES_PASSWORD` 로테이션**을 함께 처리하길 권합니다 (2026-06-19 감사에서 노출 확인 후 아직 미처리 — `CLAUDE.md` §1 대기 항목). 꾸러미의 평문 키도 그때 무력화됩니다.

---

## 3. 개발 환경 재구축

구 PC 환경: **Python 3.14.2 / Node v20.20.2 / Docker 29.2.0 / Flutter 설치됨**

```bash
cd ~/Project/Bideasy/backend
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
pytest                                                   # ← 508건 통과해야 정상 (2026-08-01 master 실측)
```

- 로컬 백엔드는 SQLite(`backend/bideasy.db`)로 동작 — 그 파일은 이관 불필요(재생성됨).
- 웹은 프레임워크 없음 — `infra/nginx/html/*.html` 직접 편집.
- **배포는 로컬 PC와 무관**합니다: ① 서버에서 `cd ~/Bideasy/infra && ./deploy.sh deploy` ② 또는 **GitHub Actions 수동 배포 워크플로**(PR #42, forced-command). 즉 새 PC 셋업 전에도 배포는 가능합니다.
- pytest가 파일 잠금으로 실패하면: 좀비 pytest 프로세스 kill 후 `backend/test.db*` 삭제 (Claude 메모리 `pytest-zombie-filedb-lock` 참고).

---

## 4. 보존한 WIP — `preserve/*` 브랜치

로컬 `git stash`와 미커밋 변경을 **원격 브랜치로 밀어뒀습니다.** clone 직후엔 안 보이니 `git fetch --all` 후 확인하세요.

| 브랜치 | 레포 | 내용 | 다루는 법 |
|---|---|---|---|
| `preserve/stash-0-settings-content-engine` | Bideasy | `.claude/settings.local.json` 권한 추가 + `docs/CONTENT_ENGINE.md` 보강 | `git diff master...preserve/stash-0-settings-content-engine` 로 보고 필요분만 반영 |
| `preserve/stash-1-bd-track-wip` | Bideasy | `BD.track` 분석 이벤트 WIP (웹 5파일: app.js·bid·calculator·login·signup) | **미완성 실험 코드** — 그대로 머지하지 말 것. 2026-05 작성분이라 이미 낡았을 수 있음 |
| `preserve/ext-toolbar-icons` | Bideasy-Extension | 툴바 아이콘 3종(16·48·128px) 교체본 | 웹스토어 재제출 시 검토 (`CLAUDE.md` 대기 항목 "툴바 아이콘 빌드") |

> stash는 커밋 객체 그대로 푸시해 **내용 손실이 없습니다.** 반영이 끝나면 브랜치를 삭제하세요.
> ⚠️ 이 3개는 **base가 2026-05~07 시점**이라 현재 master와 격차가 큽니다. cherry-pick보다 **내용을 보고 다시 작성**하는 편이 안전합니다.

### 4.1 미머지 PR — 없음

조사 시점 기준 **열린 PR은 0건**입니다. (로컬에 남아있던 `fix/web-lower-limit-tiers`는 이미 **PR #37로 머지·배포 완료** — 로컬 브랜치는 폐기 대상이었습니다.)

---

## 5. 작업 재개 지점

정본은 `CLAUDE.md` §1 "현재 상태(핸드오프)"입니다. 2026-07-30 기준 요약:

- 직전 완료: **SES 발송 파이프라인 라이브**(수신동의 증적 + 발송 원장 + 수신거부, 실발송 1통 검증) · **반송·불만 자동 억제**(PR #49) · 색인 표면 50→2,188건 · IndexNow 자동 통보 · GitHub Actions CD
- **다음**: 리드 육성 시퀀스 → 체험 시퀀스 6통 → 카카오 알림톡 채널
- ⚠️ **기존 리드·회원은 전부 미동의로 시작**(마이그 기본값 false) — **소급 발송 금지**

배포 함정(`celery_beat` 수동 force-recreate, 헬스체크 10초 오탐 등)은 `CLAUDE.md`의 "⚠️ 함정·금지 목록"을 반드시 읽으세요.

---

## 6. 이관 검증 체크리스트

`hoseung-thinkpad-x1` 기준 2026-08-01 실행 결과입니다.

- [x] 레포 4개 배치 완료 (private 2종은 bundle 경유)
- [x] `backend/.env`, `infra/.env.production.local` 복원
- [x] `PATENT.md` 복원 + `git status` clean 확인 (`.gitignore` 정상)
- [x] 전역 규칙 + 메모리 9개 복원 (SHA256 일치, SuperClaude와 병존)
- [x] `pip install -r requirements.txt` → **`pytest` 508건 통과**
- [x] Lightsail `.pem` 배치 (`~/.ssh/lightsail_bideasy.pem`, 권한 제한)
- [ ] `gh auth login` → `gh pr list` 동작 ← **잔여**
- [ ] 서버 SSH 접속 확인 / `https://api.bideasy.kr/health` 200 + `database:connected`
- [ ] **임시 SSH 키 제거** (`administrators_authorized_keys` 의 `bideasy-migration-temp-20260801`) ← **잔여**
- [ ] **OneDrive `_BIDEASY_이관/` 꾸러미 삭제** (평문 키가 클라우드에 남지 않도록) ← **잔여**

> 참고: `preserve/*` 브랜치는 clone/bundle에 포함돼 있습니다. 익스텐션의 `security/audit-2026-06-19` 는
> 원격 추적 브랜치(`origin/security/audit-2026-06-19`)로 존재하므로 `git switch -c` 로 언제든 꺼낼 수 있습니다.
