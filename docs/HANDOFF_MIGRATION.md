# BidEasy — PC 이관 인수인계서

> **맥북으로 옮기는 중이라면 → §7 로 바로 가세요.** (2026-08-04 신설. §1~§6은 Windows→Windows 기록이며, 절차의 뼈대는 그대로 유효합니다.)
>
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
| 레포 4개 | ✅ `C:\dev\bideasy-suite\` 배치 완료(§0-1 폴더 통합 반영). private 2종(`Bideasy-Extension`·`bideasy-agent`)은 gh 토큰 만료로 `git bundle` 전송 후 복원, origin URL은 GitHub으로 재설정됨 |
| 비공개 파일 5종 | ✅ `.env` 2종·`PATENT.md`·체크리스트 2건 배치. `git status` clean = `.gitignore` 정상 |
| Lightsail SSH 키 | ✅ `~/.ssh/lightsail_bideasy.pem` (소유자 읽기 전용으로 권한 제한) |
| 전역 규칙 | ✅ `~/.claude/GLOBAL_RULES_HOSI.md` + 기존 SuperClaude 진입점에 `@GLOBAL_RULES_HOSI.md` import 추가(덮어쓰기 아님, 원본은 `CLAUDE.md.bak-20260801`) |
| Claude 메모리 9개 | ✅ `~/.claude/projects/C--dev-bideasy-suite-Bideasy/memory/` — SHA256 해시 일치 검증 |
| Python 환경 | ✅ venv(Python 3.12.10) + `requirements.txt` 설치 |
| **검증** | ✅ **`pytest` 508건 전부 통과** (구 PC와 동일) |

### 📂 폴더 통합 (2026-08-01, 이관 직후 후속)

이관 후 새 PC에 `C:\Project\`(이관분)와 `C:\Projects\`(기존 작업분)가 **나란히 존재**해 혼동 위험이 컸습니다.
특히 `C:\Projects\BidEasy` 는 **2026-02-02 커밋의 6개월 낡은 사본**(behind 269 / ahead 0, 887MB)이라
최신본과 헷갈리면 사고로 이어질 상태였습니다. 그래서 `C:\dev\` 로 통합했습니다.

```
C:\dev\
  ├─ bideasy-suite\          ← BidEasy 4종 (워크스페이스 상대경로 그대로 유효)
  │   ├─ Bideasy\            ← 메인. Claude Code 는 반드시 여기서 실행
  │   ├─ Bideasy-Extension\
  │   ├─ bideasy-agent\
  │   └─ bideasy-policy\
  ├─ CoupangRankTracker\   ├─ insane-search\
  ├─ KSourceglobal\        ├─ Stardust_Sangse_Page\
  └─ _archive\bideasy-2026-02-test-scripts\   (낡은 사본에서 건진 API 테스트 6개 + 출처 메모)
```

함께 처리한 것:
- **낡은 사본 삭제** — untracked 스크립트 6개만 `_archive` 로 건지고 887MB 폴더 제거. `ahead 0` 이라 코드 유실 없음
- **venv 재생성** — Python venv 는 절대경로가 `pyvenv.cfg` 에 박혀 이동하면 깨지므로, 이동 전 삭제 후 새 위치에서 재생성
- **Claude 프로젝트 키 rename** — 경로가 바뀌면 키도 바뀌어 메모리·세션이 끊기므로 3건을 함께 이동
  `C--Project-Bideasy`→`C--dev-bideasy-suite-Bideasy`(mem 9) · `C--Projects-insane-search`→`C--dev-insane-search`(mem 2·sess 3) · `C--Projects-Stardust-Sangse-Page`→`C--dev-Stardust-Sangse-Page`(mem 3·sess 2)
- 빈 `C:\Project`·`C:\Projects` 제거

> ⚠️ 앞으로 폴더를 또 옮긴다면 **반드시 이 3가지를 세트로** 처리하세요: ① venv 재생성 ② `~/.claude/projects/` 키 폴더 rename ③ `bideasy.code-workspace` 의 `path` 확인.

### ⏳ 잔여 작업 (2026-08-01 세션에서 대부분 종료)

1. ~~`gh auth login`~~ — ✅ **이미 완료**(실측: `hosicompany` 로그인, scope `repo`·`workflow`)
2. ~~임시 SSH 키 제거~~ — ✅ **완료**(2026-08-01). `administrators_authorized_keys` 에서 `bideasy-migration-temp-20260801` 줄 삭제, `hermes-mac-to-windows-hosic` 만 남음. 백업 `administrators_authorized_keys.bak-20260801` 에 제거한 키가 들어 있으니 **이상 없음 확인 후 삭제 권장**
3. ~~OneDrive `_BIDEASY_이관\` 꾸러미 삭제~~ — ✅ 로컬에 폴더 없음 확인. 단 **웹 휴지통에 남아 있을 수 있어** 한 번 확인 권장(평문 API 키)
4. **AWS 루트 키 교체 · OpenAI 키·`POSTGRES_PASSWORD` 로테이션** — 🔴 **미처리**. 2026-06-19 감사 이후 그대로. 🚨 특히 **AWS 루트 키는 운영 서버가 지금 쓰고 있다**(2026-08-08 실측) — 폐기가 아니라 **교체**가 먼저다(`docs/SECRET_ROTATION.md` §3-1). 로컬 PC 는 무관하다(aws CLI 미설치)
5. ~~익스텐션 문서 3커밋 머지 판단~~ — ✅ **머지 완료**(2026-08-01, `main` `198f736`). 머지하면서 하네스의 구 경로 하드코딩(`C:\Project\...`)을 새 경로로 고치고 `$PSScriptRoot` 역산으로 견고화. **`& npm test` 가 `npm.ps1` shim 에서 인자가 깨져(`Unknown command: "pm"`) 게이트가 한 번도 동작한 적이 없던 것**도 함께 수정(`npm.cmd` 고정)

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
mkdir -p /c/dev/bideasy-suite && cd /c/dev/bideasy-suite && for r in Bideasy Bideasy-Extension bideasy-agent bideasy-policy; do git clone https://github.com/hosicompany/$r.git; done
```

> 경로는 **`C:\dev\bideasy-suite\` 그대로** 쓰는 것을 권장합니다. Claude Code 메모리·설정이 `C--dev-bideasy-suite-Bideasy` 키로 저장돼 있어, 경로가 바뀌면 프로젝트 히스토리가 새로 시작됩니다(위 §폴더 통합의 ⚠️ 참고).

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
| `claude-context/memory/*.md` (9개) | `~/.claude/projects/C--dev-bideasy-suite-Bideasy/memory/` | Claude 메모리 (경쟁사 3사·가격 결정·pytest 함정 등) |

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
cd /c/dev/bideasy-suite/Bideasy/backend
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

**✅ 2026-08-01 세 브랜치 모두 검토·처리 완료 — 원격에서 삭제됨.** 판정 근거:

| 브랜치 | 판정 |
|---|---|
| `preserve/stash-0-settings-content-engine` | **건질 것 없음** — `CONTENT_ENGINE.md` 는 master 가 더 최신이고, 나머지는 `.claude/settings.local.json`(개인 로컬 권한, 2026-05 시점이라 낡음) |
| `preserve/stash-1-bd-track-wip` | **건질 것 없음** — 안에 있던 `probe_bsns_div.py`·`BACKFILL_VALIDATION_DESIGN.md` 는 **master 에 이미 더 최신 버전으로 존재**. `BD.track` 자체는 미완성 실험 코드 |
| `preserve/ext-toolbar-icons` | **폐기 결정** — 아이콘 교체본은 현재 `B`+상승 모티프와 전혀 다른 **과녁(bullseye) 디자인**이었다. 과녁은 "적중·명중"의 은유라 **"낙찰가 예측은 하지 않는다"** 브랜드 포지션과 반대로 읽히고, 그건 예측형 경쟁사의 자리다. 2026-05 작성분이라 7월에 정리된 경쟁 전략 정본보다 앞선 시점의 디자인 |

> 교훈: stash 는 커밋 객체 그대로 푸시해 **내용 손실은 없었지만**, base 가 2026-05~07 이라 실제로 살릴 내용은 거의 없었다.
> 대부분은 그 사이 master 에 더 나은 형태로 들어와 있었다. 다음에 이관할 때도 **보존은 하되 기대는 낮게** 잡으면 된다.

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
- [x] `gh auth login` → `gh pr list` 동작 (2026-08-01 실측)
- [x] `https://api.bideasy.kr/health` 200 + `database:connected` (2026-08-01 실측. 배포는 GitHub Actions 버튼이라 로컬 SSH 불요)
- [x] **임시 SSH 키 제거** (2026-08-01)
- [x] **OneDrive `_BIDEASY_이관/` 꾸러미** — 로컬 부재 확인 (웹 휴지통은 사용자 확인 권장)

> **이 문서는 역할을 다했습니다.** 남은 것은 위 §잔여 4번(키 로테이션)뿐이고 그건 `CLAUDE.md` §대기 항목에도 있습니다.

> 참고: `preserve/*` 브랜치는 clone/bundle에 포함돼 있습니다. 익스텐션의 `security/audit-2026-06-19` 는
> 원격 추적 브랜치(`origin/security/audit-2026-06-19`)로 존재하므로 `git switch -c` 로 언제든 꺼낼 수 있습니다.

---

## 7. 맥북 이관 (Windows → macOS, 2026-08-04 작성)

§1~§6은 Windows→Windows 기록입니다. macOS 로 옮길 때 **달라지는 것만** 여기 정리합니다.
절차의 뼈대(§1 clone·§2 비공개 파일·§3 환경)는 그대로 유효합니다.

### 7-0. 착수 조건 — ✅ **2026-08-08 전수 점검 완료**

이관은 **작업이 걸려 있지 않을 때** 합니다. 착수 전 아래가 전부 참이어야 합니다:

```bash
git status -sb          # 4개 레포 전부 미커밋 0
gh pr list --state open # 0건

# ★ clone 으로 안 따라오는 것을 먼저 원격에 올린다 (아래 7-0-1)
for r in Bideasy bideasy-agent Bideasy-Extension bideasy-policy; do
  cd ~/dev/bideasy-suite/$r
  for b in $(git for-each-ref --format='%(refname:short)' refs/heads/); do
    n=$(git rev-list --count $b --not --remotes)
    [ "$n" -gt 0 ] && echo "미푸시 $r/$b: ${n}건"
  done
done
```

#### 7-0-1. ⚠️ 떠나기 전에 반드시 — 이걸 빠뜨리면 **조용히 유실됩니다**

clone 은 **원격에 있는 것만** 가져옵니다. 로컬에만 있는 것을 먼저 올려야 합니다.
2026-08-08 실측에서 **셋 다 실제로 걸렸습니다**:

| 대상 | 그때 상태 | 조치 |
|---|---|---|
| **Claude 메모리** | 레포 13건 / 로컬 **15건** — 갈라져 있었다 | `cd bideasy-agent/claude-memory && ./sync.sh push` → **커밋·푸시** |
| `feature/mock-bidding-phase2` | 원격에 없는 커밋 1 | `git push origin <브랜치>` |
| `preserve/ext-toolbar-icons` (익스텐션) | 원격 브랜치가 `[gone]`, 로컬 전용 커밋 1 | 〃 |

> 🚨 **`sync.sh pull` 은 `push` 가 선행돼야 의미가 있습니다.** 이 순서를 뒤집으면
> 맥에서 pull 하는 순간 이 PC 에만 있던 메모리가 사라지고, **사라진 줄도 모릅니다.**
> (메모리 폴더명은 프로젝트 절대경로에서 파생돼 기기마다 다릅니다 — §7-3 ②)

그리고 **다른 Claude 세션이 이 레포에 푸시 중이면 먼저 정리하세요.** 2026-08-03~04 에
병렬 세션이 하루 9커밋(#65~#73)을 밀어 같은 문서를 두 세션이 동시에 고친 일이 있었습니다.
이관 중에 그러면 어느 쪽이 정본인지 판정이 어려워집니다.

### 7-1. 옮기지 않아도 되는 것

| 항목 | 이유 |
|---|---|
| 레포 4개 | GitHub 에 있음 — `git clone` 이면 끝 |
| 배포 권한 | GitHub Actions 버튼(§7 배포). **로컬 SSH 불요** |
| 서버 설정 | `.env.production` 은 서버에만 존재 |
| `backend/bideasy.db`·`test.db` | 재생성됨 |
| venv | **재생성할 것** — `pyvenv.cfg` 에 절대경로가 박혀 있어 옮기면 깨집니다 |

### 7-2. 반드시 손으로 옮길 것

`.gitignore` 되어 있거나 PC 로컬에만 있어 **clone 으로 안 따라오는** 것들입니다.

2026-08-08 `--ignored` 전수 조사로 확정한 목록입니다(크기·수정일 실측).

| 항목 | 현 위치 (Windows) | 크기 | 맥 위치 |
|---|---|---|---|
| 🔒 `PATENT.md` | `Bideasy/backend/app/services/autocalibrate/` | 40K | 동일 상대경로 |
| 내부 문서 2종 | `Bideasy/MORNING_CHECKLIST.md`·`OVERNIGHT_REPORT.md` | 8K·12K | 동일 (⚠️ 내용은 2026-05-15 시점 — **이미 낡았습니다.** 이력용) |
| 로컬 개발 키 | `Bideasy/backend/.env` | 4K | 동일 |
| 운영 키 구버전 스냅샷 | `Bideasy/infra/.env.production.local` | 8K | 동일 (⚠️ 아래 경고) |
| **Lightsail SSH 키** | `~/.ssh/lightsail_bideasy.pem` | 1.6K | `~/.ssh/` + **`chmod 600` 필수** (§7-3) |
| ~~Claude 메모리~~ | — | — | ✅ **손으로 옮기지 않습니다** — `bideasy-agent/claude-memory/` 가 정본, `./sync.sh pull` (§7-3). **단 떠나기 전 `push` 선행**(§7-0-1) |
| 전역 규칙 | `~/.claude/CLAUDE.md`·`GLOBAL_RULES_HOSI.md` 등 | | `~/.claude/` |
| 힉스필드 인증 | `~/.config/higgsfield` | | 동일. 안 되면 재로그인 + `workspace set`(함정 20) |

> 익스텐션·에이전트·정책 레포에는 비공개 파일이 **없습니다**(실측). 챙길 건 `Bideasy` 하나뿐입니다.
> (익스텐션의 `bideasy-extension-v1.1.0.zip` 은 `npm run release` 로 재생성됩니다.)

#### ⚠️ `.env` 2종을 옮길 때 — 전송 방법이 중요합니다

2026-08-08 사용자 판단으로 **둘 다 옮깁니다.** 다만 `infra/.env.production.local` 은
**구버전 운영키 스냅샷**이라는 점을 알고 다루세요. 실측 내용:

- 들어 있는 것: `OPENAI_API_KEY`(164자)·`PUBLIC_DATA_KEY`·`KAKAO_*`·`NAVER_*`·
  `TOSS_WEBHOOK_SECRET`·`POSTGRES_PASSWORD`(32자)·`JWT_SECRET_KEY`
- **없는 것**: `LLM_API_KEY`·`AWS_*`·`PAYPLE_*`·`BILLING_ENC_KEY`
  → 즉 **페이플·LLM 관문 이전의 오래된 판**입니다. 현재 운영 `.env.production` 과 다릅니다.

전송 규칙:
- ⛔ **메일·카카오톡·클라우드 드라이브·채팅에 붙여넣지 마세요.** 평문 키가 영구히 남습니다
- ✅ USB 직결, 또는 `scp`/Tailscale 로 기기 간 직접 전송
- 옮긴 뒤 **두 기기 모두에 평문 키가 존재**하게 됩니다. `POSTGRES_PASSWORD`·`OPENAI_API_KEY` 는
  어차피 로테이션 대기 항목이니(`docs/SECRET_ROTATION.md` §3-2·§3-3) 이관을 계기로 정리하는 편이 낫습니다
- ⛔ 이 파일로 **서버 `.env.production` 을 덮지 마세요**(§2.1). 덮으면 결제·LLM·발송이 한 번에 죽습니다

### 7-3. macOS 에서만 걸리는 함정 4가지

1. **`.pem` 권한** — 현재 파일이 `644` 입니다. Windows 는 ACL 로 보호돼 동작하지만
   **macOS·Linux 의 ssh 는 644 키를 거부**합니다(`UNPROTECTED PRIVATE KEY FILE`).
   복사 후 반드시 `chmod 600 ~/.ssh/lightsail_bideasy.pem`.

2. **Claude 프로젝트 키가 바뀝니다** — 저장 폴더명이 프로젝트 **절대경로에서 파생**됩니다.

   | 기기 | 프로젝트 경로 | 파생 키 |
   |---|---|---|
   | Windows (현재) | `C:\dev\bideasy-suite\Bideasy` | `C--dev-bideasy-suite-Bideasy` |
   | **맥북 (확정)** | `/Users/hoseungkang/dev/bideasy-suite/Bideasy` | `-Users-hoseungkang-dev-bideasy-suite-Bideasy` |

   **자동으로 안 따라옵니다.** → **2026-08-04 해소**: 메모리 정본을 private 레포로 승격했습니다.
   손으로 복사하지 말고 아래 한 줄을 돌리세요(키 파생은 스크립트가 양 플랫폼에서 처리합니다).
   ```bash
   cd ~/dev/bideasy-suite/bideasy-agent/claude-memory && ./sync.sh pull
   ```

   > 🚨 **대소문자를 섞지 마세요 — 폴더의 실제 이름과 입력하는 이름이 같아야 합니다.**
   > 취향 문제가 아니라 **조용한 실패의 원인**입니다.
   >
   > Claude 키는 경로 **문자열**에서 파생되므로 대소문자를 가립니다(2026-08-08 `sync.sh` 실측):
   > ```
   > /Users/hoseungkang/dev/…  →  -Users-hoseungkang-dev-bideasy-suite-Bideasy   ← 정본
   > /Users/hoseungkang/Dev/…  →  -Users-hoseungkang-Dev-bideasy-suite-Bideasy   ← 다른 폴더
   > ```
   > 그런데 macOS 기본 파일시스템(APFS)은 대소문자를 **구분하지 않고 보존**합니다. 그래서
   > 이름이 어긋나도 `cd` 는 **에러 없이 성공**하고, 메모리 0건인 새 프로젝트가 조용히 열립니다.
   > "안 보인다"와 "없다"가 구분되지 않는 그 실패 모드입니다(§7-0-1 과 같은 부류).
   >
   > **2026-08-08 결정: 소문자 `dev` 로 통일합니다.** 원래 `~/Dev` 였던 것을 사용자가 `~/dev` 로
   > rename 했습니다 — 앞으로 생길 다른 프로젝트까지 고려하면 오타 여지가 적은 쪽이 낫다는 판단.
   >
   > ⚠️ **rename 했다면 Claude 키 폴더도 함께 옮겨야 합니다.** 폴더 안에 있던 다른 프로젝트 중
   > 맥에서 Claude Code 로 열어본 적이 있는 것들은 옛 대문자 키에 기록이 남아 있습니다.
   > (레포·venv 는 무사합니다 — git 은 상대경로, venv 는 대소문자 무시로 그대로 찾아갑니다.)
   > ```bash
   > ls ~/.claude/projects/ | grep -- '-Users-hoseungkang-Dev-'   # 없으면 조치 불필요
   >
   > cd ~/.claude/projects
   > for d in -Users-hoseungkang-Dev-*; do
   >   [ -e "$d" ] || continue
   >   new="${d/-Dev-/-dev-}"
   >   if [ -e "$new" ]; then echo "⚠️ 양쪽 존재, 수동 확인: $d vs $new"
   >   else mv -- "$d" "$d.tmp" && mv -- "$d.tmp" "$new" && echo "✅ $d → $new"; fi
   > done
   > ```
   > `mv` 를 두 번 나누는 이유: 대소문자만 바뀌는 rename 은 같은 파일로 취급돼 무시될 수 있습니다.

   경로 구조(`bideasy-suite/` 아래 형제 4개)도 그대로 지켜야 워크스페이스 상대경로와
   `sync.sh` 의 형제 폴더 자동 탐지가 삽니다.

3. **venv 활성화 경로** — `source .venv/bin/activate` 입니다(Windows 의 `Scripts/` 아님).

4. **PowerShell 훅은 못 씁니다** — 익스텐션 레포의 검증 훅이 PowerShell 기반입니다.
   맥에선 sh 로 재작성해야 합니다. 참고: 그 훅은 `& npm` shim 문제로 한동안 무동작이었습니다(§잔여 5).

### 7-4. 이관 후 검증

```bash
# ⚠️ macOS 의 python3 은 버전이 제각각이라 3.12 를 명시한다 (없으면 brew install python@3.12)
cd ~/dev/bideasy-suite/Bideasy/backend
python3.12 -m venv .venv && source .venv/bin/activate    # Windows 의 Scripts/ 아님
pip install -r requirements.txt && pytest        # 통과 건수는 CLAUDE.md §8 기준

# ⚠️ ruff 는 requirements.txt 에 없다 — CI 도 `pip install ruff` 로 따로 깐다(.github/workflows)
pip install ruff && python -m ruff check .
```

> **2026-08-08 실측(`apples-MacBook-Pro`, Apple Silicon)**: 전부 휠로 설치돼 컴파일 0,
> `pytest` **824 passed / 23초**. 같은 코드가 Windows 에서 128초였다 — **5.5배** 빠르다.

- [ ] 레포 4개 clone, `git status` clean (= `.gitignore` 정상 = 비공개 파일 복원됨)
- [ ] **4개가 `/Users/hoseungkang/dev/bideasy-suite/` 아래 형제 폴더**인지 — 워크스페이스 상대경로와 `sync.sh` 자동탐지가 여기 의존
- [ ] `cd ~/dev/bideasy-suite/Bideasy && pwd` → **`/Users/hoseungkang/dev/...` (대문자 D)** 로 나오는지 (§7-3 ②)
- [ ] `gh auth login` → `gh pr list` 동작
- [ ] `ssh -i ~/.ssh/lightsail_bideasy.pem ubuntu@api.bideasy.kr 'echo ok'` (권한 600 확인)
- [ ] `bideasy-agent/claude-memory/./sync.sh status` → **차이 없음 ✅** (메모리 동기화 확인)
- [ ] 메모리 **건수**가 떠나기 전과 같은지 (2026-08-08 기준 **15건**). 줄었으면 §7-0-1 을 빠뜨린 것
- [ ] `curl -s https://api.bideasy.kr/health` → `status:ok`·`database:connected`
- [ ] 전역 `~/.claude/CLAUDE.md` §5 의 BidEasy 정본 경로를
      **`/Users/hoseungkang/dev/bideasy-suite/Bideasy/CLAUDE.md`** 로 수정
      (현재 `C:\Project\Bideasy\CLAUDE.md` 로 적혀 있어 **윈도우에서도 이미 틀린 경로**입니다)

### 7-5. 옮기지 말 것

- **`infra/.env.production`** — 서버에만 존재합니다. 로컬 스냅샷(`.local`)으로 서버를 덮지 마세요.
- **`BILLING_ENC_KEY`** — 이관을 이유로 재생성하는 일이 없어야 합니다. 변경 시 고객 빌링키 전부 복호화 불가.
- **AWS 자격증명**(`~/.aws/credentials`) — 새 PC 로 복사하지 말고 필요할 때 IAM 콘솔에서 새로 발급하세요.
  🚨 특히 지금은 **운영 서버가 루트 키로 돌고 있는 상태**라(`CLAUDE.md` §대기 항목 최상단) 자격증명을
  기기에 퍼뜨릴 때가 아닙니다. 교체가 먼저입니다 — `docs/SECRET_ROTATION.md` §3-1.
- **로컬 SQLite**(`bideasy.db`·`backend/bideasy.db`, 합계 ~700K) — 재생성됩니다. 테스트는 in-memory 라 없어도 통과.
- **`node_modules`·`.venv`·`__pycache__`·`dist`** — 재설치. venv 는 `pyvenv.cfg` 에 절대경로가 박혀 있어 옮기면 깨집니다.
- **orca 워크트리**(`~/orca/workspaces/Bideasy/*`) — 2026-08-08 기준 3개(`master`·`work`·`infra-cost-analysis-lightsail`).
  브랜치 내용은 전부 원격에 있으므로 clone 으로 복원됩니다. 단 `blog` 워크트리의 untracked
  `_content_review/`(7.8MB, 32파일)는 **생성 부산물**이라 옮기지 않습니다 — 필요하면 재생성하세요.
