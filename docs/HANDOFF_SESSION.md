# 세션 인수인계 — 다른 IDE·다른 에이전트로 이어받기

> 작성 2026-08-08 · 갱신 2026-08-10. 기준: draft PR #98 `fix/mock-bidding-recovery` (원격 `6b9b841` + 리뷰 보완 로컬 변경, 미push·미머지·미배포) / 운영 `bacda36`.
> **대상**: Claude Code 가 아닌 다른 IDE·에이전트(Cursor / VS Code Copilot / Codex / 다른 세션)로
> 작업을 이어받는 사람.
>
> 이 문서는 **"지금 어디까지 왔고 다음에 뭘 하면 되는가"** 만 다룹니다.
> **규칙·함정·아키텍처의 정본은 여전히 루트 `CLAUDE.md`** 입니다 — 여기 내용을 복사하지 않습니다.
> 갈리면 `CLAUDE.md` 가 이깁니다.

---

## 0. 30초 요약

**BidEasy = 공공 입찰(나라장터/G2B) 분석·투찰 비서.** 크롬 익스텐션 + 웹앱 + 공유 FastAPI 백엔드.
포지션은 **"낙찰가를 예측하지 않는다"** — 대신 요약·독소조항·자격·안전 계산으로 *잃지 않게* 지킨다.

지금 상태를 한 문장으로: **코드와 인프라는 앞서 있고, 실사용자가 없다.**
(테스트 847건 green · 그런데 리드 1명 / 회원 2명)

그래서 다음 작업의 우선순위는 이렇게 갈립니다:

| 순위 | 무엇 | 왜 |
|---|---|---|
| 1 | ~~🚨 AWS 루트 키 교체~~ → **루트 키 폐기** | 08-09 재정정: 서버는 발송 전용 키를 쓴다 — 오경보였다 (§3) |
| 2 | ~~#90 배포~~ ✅ 완료 | 08-08 15:35 KST 배포됨 — 08-09 확인 (§6) |
| 3 | 모의투찰 큐 수정 배포·G-A 복구 관찰 | G-A 27.98%, 유효 표본 59공고라 성능 해석 차단 중 |
| 4 | 기초금액 커버리지 관찰 | 방금 고친 것이 실제로 듣는지 (§5-A) |
| 5 | 유입 / 고객 검증 | 진짜 병목. 코드로 풀 문제가 아닐 수 있다 (§5-C) |

### 2026-08-10 모의투찰 정정

종전 “SCORED 2,275건이므로 2026 G2 400건 충족”은 틀렸다. `mock_bids` 한 공고에
5 arm 행이 생기는데 이를 표본 5개로 셌고, 기초금액 기준 불일치도 제거하지 않았다.
운영 재실측은 **1,773공고 등록 / 496공고 확정 / G-A 27.98% / 유효 59공고 /
적격 유효 2공고**다. G-B·G2 모두 아직 `NOT_READY`다.

로컬 변경은 큐 우선순위, 데이터 품질 가드, G-A/B/C 자동 판정, 관리자 잠금,
월 21:00 주간 리포트, 2026 G2 CLI까지 구현했다. **아직 운영에는 없으므로** 다음
세션이 서버 수치가 그대로라고 코드를 실패로 판정하면 안 된다. 사용자 승인 후 배포하고
`queue_health`의 결과도착/최초확인 잔량부터 관찰한다. 상세는
`docs/MOCK_BIDDING_DESIGN.md` §9.

---

## 1. 좌표 — 어디에 무엇이 있나

```
Windows : C:\dev\bideasy-suite\                 (Claude 키 C--dev-bideasy-suite-Bideasy)
macOS   : /Users/hoseungkang/dev/bideasy-suite/ (Claude 키 -Users-hoseungkang-dev-bideasy-suite-Bideasy)
├── Bideasy/                     ★ 메인. backend + infra + 웹 정적 + 문서. PUBLIC 레포
├── Bideasy-Extension/           크롬 익스텐션 (TypeScript). 별도 레포
├── bideasy-agent/               운영 에이전트 + Claude 메모리 정본. PRIVATE
└── bideasy-policy/              개인정보처리방침 등 정책 문서
```

> 🚨 **맥은 소문자 `dev` 로 통일합니다**(2026-08-08 결정, 원래 `~/Dev` 를 rename).
> Claude 키는 경로 **문자열**에서 파생돼 대소문자를 가리는데, APFS 는 대소문자를 **구분하지 않아**
> 이름이 어긋나도 `cd` 가 에러 없이 성공합니다 → **메모리 0건인 새 프로젝트가 조용히 열립니다.**
> 폴더의 실제 이름과 입력하는 이름을 항상 같게 두세요 — `docs/HANDOFF_MIGRATION.md` §7-3 ②.

`Bideasy\bideasy.code-workspace` 를 열면 4개가 한 창에 붙습니다(상대경로 참조 — 폴더를 옮기면 이 파일도 함께 고칠 것).
Python 인터프리터는 `${workspaceFolder:Bideasy — backend · web · flutter}/backend/.venv`로 OS 중립 지정돼 있고,
백엔드 task는 macOS `bin/python` / Windows `Scripts\\python.exe`를 각각 사용한다.
macOS에서 workspace가 `Scripts/python.exe`를 가리키면 시스템 Python 3.14로 폴백해
`pytest`가 없다고 나오므로 경로를 먼저 확인한다.

> ⚠️ **병렬 세션이 돌고 있을 수 있습니다.** `git worktree list` 로 확인하세요.
> 2026-08-08 기준 `C:\Users\hosic\orca\workspaces\Bideasy\` 아래에 워크트리 3개(`master`·`work`·
> `infra-cost-analysis-lightsail`)가 살아 있습니다. 실제로 이 문서를 쓰는 동안 다른 세션이 #90 을
> master 에 올려 충돌이 났습니다.
> → **판단·커밋 직전마다 `git fetch` 를 다시 돌리세요.** 세션 시작 때 한 번으로는 부족합니다.

### 각 레포의 현재 위치 (2026-08-08 실측, 전부 clean · 원격과 동기)

| 레포 | 브랜치 | HEAD | 비고 |
|---|---|---|---|
| Bideasy | `master` | `99199f9` (#90) | ✅ 운영 = `99199f9` — #90 은 08-08 15:35 KST 배포 완료, 마이그 `f7c4a2e18b53` 적용(08-09 확인) |
| Bideasy-Extension | `feat/diagnose-cta` | `fa0b464` | ⚠️ **`main`(`198f736`)에 미병합.** 웹스토어 v1.1.0 은 이 브랜치로 제출됨 |
| bideasy-agent | `master` | `beae87a` | |
| bideasy-policy | `main` | `e80f2cb` | |

### 읽는 순서 (처음이라면)

1. `CLAUDE.md` — **전체.** 특히 맨 위 「최종 갱신」 문단들과 **「⚠️ 함정·금지 목록」 22개**
2. 이 문서 (`docs/HANDOFF_SESSION.md`)
3. `git log --oneline -30`
4. 손댈 영역의 설계 문서 하나 (→ §7 지도)

`CLAUDE.md` 는 깁니다. 그래도 **함정 목록만은 건너뛰지 마세요** — 그 22개는 전부 실제로 한 번씩
사고가 났던 항목입니다. 특히 **함정 22(기초금액)** 는 지금 작업의 한복판입니다.

---

## 2. 환경 셋업 (다른 IDE·다른 OS)

```bash
git clone https://github.com/hosicompany/Bideasy.git
cd Bideasy
pip install -r backend/requirements.txt      # Python 3.12
cd backend && pytest                          # 847건 통과해야 정상
pip install ruff && python -m ruff check .    # ⚠️ ruff 는 requirements.txt 에 없다 (CI 도 따로 깐다)
```

> macOS 는 `python3.12 -m venv .venv && source .venv/bin/activate` (Windows 의 `Scripts/` 아님).
> 실측 참고: Apple Silicon 에서 `pytest` 847건이 **24초**(2026-08-10).

- **서버 SSH 키는 없어도 됩니다.** 배포는 GitHub Actions 버튼(§6).
- `backend/.env`·`backend/bideasy.db` 는 git 에 없습니다 — 테스트는 in-memory 라 없어도 통과합니다.
- `infra/.env.production` 은 **서버에만** 있습니다. 절대 로컬로 복사하지 마세요.
- **옮기지 말 것**: `PATENT.md`, `MORNING_CHECKLIST.md`, `OVERNIGHT_REPORT.md` (`.gitignore` 등재).
- macOS 로 옮기는 경우의 차이(=`python3`·`bin/activate`·CRLF·권한)는 `docs/HANDOFF_MIGRATION.md` §7.

### 다른 에이전트를 쓴다면

- 루트 `AGENTS.md` 가 포인터입니다 — 내용은 `CLAUDE.md` 에만 둡니다(복사하면 갈라집니다).
- **완료 보고는 4항목 고정**: 변경 파일 / 실행한 검증(명령+결과) / 신뢰도 🟢🟡🔴 / 미해결 사항.
  검증을 안 돌렸으면 "미실행"이라고 **명시**하고, 🔴 상태에서 "완료됐습니다"라고 하지 않습니다.
- **Claude 메모리**는 `bideasy-agent/claude-memory/` 가 정본입니다. 다른 IDE 는 이걸 안 읽으므로,
  거기 있는 판단 근거가 필요하면 직접 열어 보세요(`./sync.sh status` 로 로컬 사본과 대조).

---

## 3. 🚨→✅ "루트 키가 운영에서 쓰인다"는 오경보였다 (2026-08-09 재정정)

이 문서의 08-08 초판은 "운영 컨테이너의 `AWS_ACCESS_KEY_ID` 가 AWS 루트 계정 액세스 키"라고
적었습니다. **오판이었습니다.** 2026-08-09 재실측:

| 키 | ID | 마지막 사용 |
|---|---|---|
| 루트 키 | `AKIAY5OAWO54LAO73L7F` (04-21 생성) | 08-07 `aws-mcp`(us-east-1) — **SES 아님** |
| 발송 전용 `bideasy-ses-sender` | `AKIAY5OAWO54BXS3VHTO` (07-30 생성) | 08-04 `ses`(서울) = 서버 발송 |
| **서버 컨테이너 (실측)** | 끝 4자 **`VHTO`** | → **발송 전용 키와 일치** |

**서버는 처음부터 설계(07-30)대로 발송 전용 IAM 키를 쓰고 있었습니다.**

오판의 원인: 확인 명령이 `cut -c1-32`(키 14자)였는데, **같은 계정의 액세스 키는 앞 12자
(`AKIAY5OAWO54`)를 공유**합니다 — 그 범위에는 루트/IAM 을 가를 식별력이 없습니다.
**키 대조는 끝 4자(`tail -c 5`)나 `aws iam get-access-key-last-used` 로 하세요.**

### 그래도 남은 일 — 루트 키 자체의 폐기

루트 키는 여전히 **Active** 이고, **맥북 `~/.aws/credentials` [default] 에 평문**으로 있으며,
aws-mcp 라는 MCP 도구가 쓰고 있습니다(08-07 사용 흔적). 루트 키는 MFA 로도 권한 축소가 불가능한
전권이라 존재 자체가 위험입니다.

순서 = **소비자(aws-mcp)를 최소 권한 IAM 사용자 키로 이전 → 루트 키 비활성화 → 2~3일 관찰 → 삭제
+ 루트 MFA 활성화 확인**. 절차 = `docs/SECRET_ROTATION.md` §3-1(08-09 재정정).

> **에이전트에게**: 이 작업에서 비밀키 **값**을 채팅·파일·커밋에 남기지 마세요.
> 읽어도 되는 것은 **키 이름·문자 길이·키 ID**(비밀값 아님)까지입니다.
> 키 발급과 설정 교체는 사람이 합니다(🔴 등급). 조회·검증·문서 정정은 에이전트가 해도 됩니다.

### 판정이 두 번 뒤집힌 경위 (반복 금지)

08-01 판 "서버는 발송 전용 IAM 을 쓴다"는 근거가 로컬 PC 점검뿐이었고 →
08-08 판 "루트 키다"는 실측은 했으나 **식별력 없는 지표**(14자 접두사)로 반대 방향으로 틀렸으며 →
08-09 에 끝 4자·사용 이력으로 확정하고 6곳을 재정정했습니다.
→ **"실측"은 지표가 대상을 실제로 식별할 수 있을 때만 실측입니다.**

---

## 4. 현황을 직접 재확인하는 법

문서의 숫자는 늙습니다. **판단하기 전에 직접 재세요.**

### 운영 DB 스냅샷

```bash
# 로컬 파일을 서버에 남기지 않고 흘려보낸다
ssh -i ~/.ssh/lightsail_bideasy.pem ubuntu@api.bideasy.kr \
    'docker exec -i bideasy_app python -' <<'PY'
from app.db.session import SessionLocal
from sqlalchemy import text
db = SessionLocal()
def q(l, s):
    try:
        for r in db.execute(text(s)).fetchall(): print(f"{l}: {tuple(r)}")
    except Exception as e:
        db.rollback(); print(f"{l}: ERR {str(e)[:120]}")
q("공고", """select count(*), count(basis_amount),
     count(*) filter (where end_date > now()),
     count(*) filter (where end_date > now() and basis_amount is not null) from notices""")
q("A값출처", "select a_value_source, count(*) from notices where a_value is not null group by 1")
q("모의투찰 arm행", "select status, count(*) from mock_bids group by 1")
q("모의투찰 공고", """select count(distinct bid_no),
     count(distinct bid_no) filter (where status='SCORED'),
     round(100.0 * count(distinct bid_no) filter (where status='SCORED') /
           nullif(count(distinct bid_no), 0), 2) from mock_bids""")
q("모의투찰 유효표본", """with latest as (
     select distinct on (mock_bid_id) mock_bid_id, outcome, actual_reserved_price
     from mock_bid_results order by mock_bid_id, scoring_rev desc)
     select count(*) filter (where l.outcome in ('WIN','LOST','DROPOUT')) raw_judged,
            count(*) filter (where l.outcome in ('WIN','LOST','DROPOUT') and
              l.actual_reserved_price / nullif(m.snapshot_basic_price,0) between 0.94 and 1.06) valid
     from mock_bids m join latest l on l.mock_bid_id=m.id where m.arm='active'""")
q("개찰", "select count(*), min(open_date)::date, max(open_date)::date from opening_results")
q("리드/회원", "select (select count(*) from leads), (select count(*) from users)")
q("발송원장", "select status, count(*) from outbound_messages group by 1")
db.close()
PY
```

`docker exec` 여야 합니다 — `docker compose exec` 는 **지금의 `--env-file` 을 새로 주입**해서
재배포 전에도 "반영됨"으로 보입니다(`CLAUDE.md` 함정 21). 환경변수 확인도 `/proc/1/environ` 으로:

```bash
docker exec bideasy_app sh -c 'tr "\0" "\n" < /proc/1/environ | grep ^AWS_ACCESS_KEY_ID= | tail -c 5'
# 키 대조는 끝 4자로 — 앞자리는 같은 계정 키끼리 겹친다 (§3)
```

### 그 외 한 줄들

```bash
curl -s https://api.bideasy.kr/health        # status:ok · database:connected · redis:connected
ssh …  'cd ~/Bideasy && git log --oneline -1'        # 서버가 어느 커밋인지
ssh …  'docker exec bideasy_app alembic current'     # 마이그레이션 head
```

2026-08-08 기준값은 `CLAUDE.md` 「📊 운영 실측 스냅샷」에 표로 있습니다. 그것과 비교하세요.

---

## 5. 진행 중인 작업 세 갈래

### A. 기초금액 2층-B — 수집·소비 완료, **관찰 단계**

가장 최근까지 붙잡고 있던 줄기입니다. 배경은 `docs/PRICE_BASE_DEFECT.md`.

**무슨 일이었나**: `Notice.basic_price` 에 든 값이 기초금액이 아니라 **추정가격**(부가세 제외)이었습니다.
실제 기초금액은 약 1.1배. 그대로 계산하면 사용자에게 **낙찰하한선이 9% 낮게** 나갑니다 — 즉
적자 투찰을 "안전"이라고 말하게 됩니다. 함정 22.

**어디까지 했나**:
- #78 전용 API(`…CnstwkBsisAmount` → `bssamt`)로 **수집 시작**. `basic_price` 는 **덮지 않는다**
  (커버리지 미달 상태에서 덮으면 한 컬럼에 또 두 기준이 섞인다 — 그게 원래 사고의 원인)
- #80 소비를 `BASIS_AMOUNT_ENFORCE` 스위치로 분리. 판정은 **`services/basis.py` 한 곳에만**.
  ON 이면 미확인 공고는 숫자를 **숨기고 "모른다"고 말한다**. **현재 서버 ON.**
- #88 조회 창 3일 → **14일**(커버리지 9.3% → 75.3% 실측). 개찰 후에는 개찰 API 의 `bssAmt` 도 소스로 인정.

**지금 할 일**: 진행중 공고의 기초금액 보유율(2026-08-08 = **13.5%**)이 오르는지 §4 로 재봅니다.
#88 이 08-06 배포라 아직 차오르는 중입니다.

⚠️ **안 오르면 창을 더 넓히기 전에 다른 축을 의심하세요.** 08-06 에 정확히 이 함정을 밟았습니다 —
"수집 주기(06:40)가 병목"이라 진단했는데, 그때 본 09~11시 집중은 *하루 안의 시각 분포*였고
진짜 병목은 *조회 창*이었습니다. **두 축을 혼동한 것.**

⛔ **`× 1.1` 하드코딩 금지.** 실측 산포가 1.0746~1.1111 이라 면세·단가계약에서 깨집니다.

### B. 아웃바운드 이메일 — 파이프라인 완성, **물량이 없음**

법적 요구사항까지 닫혀 있습니다(동의 증적 → 더블 옵트인 → 발송 원장 → 수신거부 → 처리결과 통지).
런북 `docs/OUTBOUND_EMAIL.md`.

발송 원장 8건이 전부입니다. **코드 문제가 아니라 대상이 없는 것.**
남은 미실증 하나: `trial.send_onboarding_sequence`(D1, 매일 10:10)는 대상 회원이 없어 아직 한 번도
발송된 적이 없습니다. 새 가입자가 생기면 자동으로 첫 판정이 납니다.

**손대기 전에 반드시 읽을 것 — `CLAUDE.md` 함정 10~17.** 요약하면:
- 발송은 `services/nurture.py` **유일 진입점**으로만. `mailer.send()` 직접 호출 금지(동의 게이트·원장 우회)
- **거래 메일에 할인·권유 문구를 끼우면 그 메일 전체가 광고물**이 되어 위법 발송이 됩니다
- 동의 없는 연락처에 광고 금지, **소급 동의도 금지**(2026-07-30 이전 리드는 증적이 없음)
- 멱등 키 주체는 **행이 아니라 수신자**(이메일 sha1)

### B-2. 누적 개찰 통계 S1 — 머지·**배포 완료**(08-08 15:35 KST, 08-09 확인), S2 미착수

#90(`99199f9`). 설계 정본 `docs/OPENING_STATS_DESIGN.md`.
`opening_results` 원장을 축(기관 × 입찰방법 × 금액대)으로 묶어 **분위수만** 남기는 `opening_stats` 표
+ 매일 19:30 재집계. 경쟁 3사 누구도 안 주는 정보인데 재료는 이미 갖고 있었습니다.

**S2(화면)는 미착수.** 드라이런상 진행중 공사 1,699건 중 66.3%가 셀을 찾고, 병목은 통계가 아니라
**기초금액 미확인 30.8%** — 즉 §5-A 와 묶여 있습니다.

⛔ **평균을 담지 않습니다.** 사정률 평균이 전 기관 99.84~100.05% 라 신호가 없는데,
담아 두면 화면이 "이 기관 사정률은 99.84%"로 읽고 그건 **낙찰가 예측처럼 보입니다.**
⛔ `winner_rate_*` 는 낙찰자의 **투찰률**이지 이길 확률이 아닙니다 — '낙찰률'로 부르면 거짓 지표가 생깁니다(함정 2).

### C. 유입·고객 검증 — **진짜 병목**

리드 1명 / 회원 2명. 인프라(SEO 색인 2,188건·IndexNow·블로그 9편·리드 마그넷·익스텐션 진단 CTA)는
다 깔았는데 사람이 안 옵니다.

- 전략 정본 `docs/GROWTH_STRATEGY.md` — **판정 기준·킬 기준이 §7 에 사전 등록**돼 있습니다(사후 합리화 금지)
- 유입 효과 판정 예정일이 **2026-08-13 경**이었습니다. 지금 서치콘솔·서치어드바이저·GA4 를 보고 판정할 시점입니다
- 광고 A/B 패키지는 완성돼 있고 **집행 보류 중** — `docs/AD_CAMPAIGN_VALIDATION.md`
- 비치헤드: 전문건설(전기공사 먼저) 1~10인, 월 10건+ 직접 투찰

> **여기가 이 프로젝트에서 가장 정직해야 하는 지점입니다.** 기능을 더 만드는 건 쉽고 즐겁지만,
> 지금 부족한 건 기능이 아닙니다. 새 기능을 제안하기 전에 `docs/COMPETITIVE_STRATEGY.md` 를 통과시키세요.

---

## 6. 검증과 배포

### 코드 변경 후 (예외 없음)

```bash
cd backend && pytest              # 847건 기준
python -m ruff check backend/     # 미사용 import 하나로 CI 가 red 가 된다
```

실패 상태로 커밋·배포 금지. 수정은 **2회까지**, 그래도 실패하면
[실패 지점 / 원인 추정 / 시도한 것]을 정리해 사람에게 넘깁니다. 같은 접근을 반복하지 않습니다.

### LLM 을 건드렸다면 — 목킹 테스트로 끝내지 말 것

`CLAUDE.md` §8-1 의 실호출 probe 를 돌립니다. 테스트 605건이 전부 green 인 상태에서
정본 모델이 **한 번도 성공한 적이 없던** 사례가 실제로 있었습니다(추론형 모델이 `max_tokens` 를
reasoning 으로 다 써서 빈 응답). 새 LLM 호출부는 반드시 `services/llm_gateway.py` 를 지나야 합니다.

### 배포

✅ **08-09 정정: #90 은 08-08 15:35 KST 에 배포 완료**됐습니다(Actions run head `99199f9`,
마이그레이션 `f7c4a2e18b53` 적용). 현재 master 의 미배포분은 문서 커밋(#91~#95 + 이 재정정)뿐이라
급하지 않습니다.

**기본 = GitHub Actions 버튼**: Actions → *Deploy to production* → Run workflow.
master 의 `test`+`build` 가 green 이어야만 진행되고(우회 플래그 없음), 배포 후 워크플로가
`/health`·`bideasy.kr`·`sitemap.xml` 을 직접 검증합니다. 상세 = `docs/DEPLOY_CD.md`.

서버 직접: `cd ~/Bideasy/infra && ./deploy.sh deploy` (pull → build → 롤링 재시작 → 헬스체크 → `alembic upgrade head`).

- ⚠️ 배포 직후 `WARNING: Health check failed` 는 대개 **오탐**(10초 뒤 체크). 진짜 상태는 `/health`.
- 🟡 배포는 확인 후 진행 등급입니다. 사람에게 알리고 하세요.

### PR

- **문서·설정 전용 PR(코드 변경 0)만 자동 머지 가능.**
- **코드 변경이 포함된 PR 은 머지 전 반드시 사람 확인.**
- `git push` 는 매번 사람의 명시 승인 후.

---

## 7. 문서 지도 — 무엇을 만질 때 무엇을 읽나

| 손대는 영역 | 먼저 읽을 문서 |
|---|---|
| 기초금액·낙찰하한선·계산 | `docs/PRICE_BASE_DEFECT.md` ⚠️ 필수 |
| 모의투찰·백테스트·전략 판정 | `docs/MOCK_BIDDING_DESIGN.md` · `docs/BENCHMARK_WIN_REACH.md` |
| 이메일·동의·수신거부 | `docs/OUTBOUND_EMAIL.md` (+ 함정 10~17) |
| 리드·진단·퍼널 | `docs/LEAD_ACQUISITION.md` |
| 블로그·콘텐츠·검수 게이트 | `docs/CONTENT_ENGINE.md` · `docs/BLOG_RUNTIME_PUBLISHING.md` |
| SEO·유입 | `docs/GROWTH_STRATEGY.md` · `docs/SEO_CHECKLIST.md` |
| 새 기능 제안 | `docs/COMPETITIVE_STRATEGY.md` — **통과 필수** |
| 배포·CI | `docs/DEPLOY_CD.md` |
| 비밀키 | `docs/SECRET_ROTATION.md` |
| 웹스토어 listing | `docs/STORE_LISTING.md` |
| 다른 PC·OS 로 이관 | `docs/HANDOFF_MIGRATION.md` |
| 장애 대응 | `docs/TROUBLESHOOTING.md` |
| 입찰 용어 | `docs/GLOSSARY_BIDDING.md` |

---

## 8. 이 프로젝트에서 반복적으로 데인 것들

함정 22개 전체는 `CLAUDE.md` 에 있습니다. 그중 **문서를 안 읽어도 몸에 배어야 하는** 넷:

**① 테스트 통과 ≠ 작동.**
800건 넘게 green 인 상태에서 — 크롤러가 매일 같은 500건만 긁고 신규를 하나도 못 가져오고 있었고,
정본 LLM 모델은 한 번도 성공한 적이 없었고, 검수 게이트는 실발행 4편을 100% 오탐했습니다.
외부와 만나는 것(API·LLM·메일·브라우저)은 **실호출로만** 증명됩니다.

**② 운영 로그는 이미 말하고 있다.**
`fetched:500 saved:0`, `no_notice:515`, `NumericValueOutOfRange` — 전부 로그에 있었는데
아무도 안 봤습니다. 이상하면 코드보다 로그를 먼저 읽으세요.

**③ 다른 레포·다른 화면의 상태를 추측하지 말 것.**
2026-08-06 하루에 백로그 **유령 항목 3개**가 폐기됐습니다. 셋 다 원인이 같습니다 —
해당 레포를 열어보지 않고 적은 것. 웹스토어 listing 4곳도 코드와 따로 놀다 거짓이 됐습니다.
**"레포에 없다"는 "존재하지 않는다"의 증거가 아닙니다.**

**④ 지표가 상식을 벗어나면 모델보다 데이터의 단위·기준을 먼저 의심할 것.**
`basic_price` 한 컬럼에 두 기준(기초금액/추정가격)이 섞여 있던 걸 찾는 데 오래 걸렸습니다.

그리고 **절대 금지** 둘만 다시:
- ⛔ **`BILLING_ENC_KEY` 변경·재생성 금지** — 바꾸는 순간 고객 빌링키 전부 복호화 불가.
- ⛔ **KPI·마케팅 문구에 '낙찰률' 사용 금지** — 핵심 지표는 유효율과 재사용률.
  (실제로 검수 게이트가 이 위반을 블로그 글에서 잡아낸 적이 있습니다.)

---

## 9. 이어받는 사람에게 남기는 한 가지

이 프로젝트의 문서는 길지만, 긴 이유는 **결정의 근거**를 적기 때문입니다.
"무엇을 했다"보다 **"왜 그렇게 했고, 무엇을 안 했는가"** 가 더 많습니다.
그게 이 코드베이스에서 같은 실수를 두 번 하지 않게 해 온 유일한 장치입니다.

그러니 작업을 마치면 `CLAUDE.md` 의 「최종 갱신」 문단을 갱신해 주세요.
**틀렸던 판단을 정정한 기록**은 특히 값집니다 — 이번 갱신의 절반이 그것입니다.
