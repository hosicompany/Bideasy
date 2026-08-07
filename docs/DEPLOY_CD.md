# 배포 자동화 (GitHub Actions 수동 버튼)

> 작성 2026-07-27 · 최종 확인 2026-08-08 · 상태: **운영 적용 완료**
> 목적: `ssh → cd ~/Bideasy/infra → ./deploy.sh deploy` 를 매번 손으로 하는 대신, GitHub 화면의 **Run workflow 버튼 한 번**으로 끝낸다. 배포 타이밍은 사람이 정한다(자동 배포 아님).

### 현재 프로덕션 인프라 (2026-08-08)

| 항목 | 현재 값 |
|---|---|
| Lightsail 인스턴스 | `BidEasy-prod-2gb` (2GB RAM / 2 vCPU / 60GB SSD, 월 $12 플랜) |
| 고정 IP | `43.203.66.120` |
| 이전 인스턴스 | `BidEasy-prod`(4GB) — 전환 검증 후 삭제 완료 |
| 롤백 스냅샷 | `BidEasy-prod-pre-downsize-20260808` — 2026-08-15까지 보관 후 수동 삭제 대상 |

인스턴스 교체 후 앱·PostgreSQL·Redis·Celery와 라이브 헬스체크를 확인했고, GitHub Actions 배포도 성공했다. 고정 IP는 유지했지만 SSH 호스트 키는 바뀌었으므로 아래 `DEPLOY_KNOWN_HOSTS` 값이 정본이다.

---

## 0. 이 방식의 요지

```
[GitHub Actions "Deploy (production)" 버튼]
   │  ① master 커밋 확인
   │  ② 그 커밋의 CI(test·build) 성공 여부 검사 → 실패면 배포 중단
   │  ③ 배포 전용 키로 SSH
   ▼
[Lightsail]  ~/deploy-agent.sh   ← forced command (이 키로는 이것만 실행 가능)
   │  deploy | indexnow-backfill | status | health  중 하나만 허용
   ▼
  ./deploy.sh deploy   (git pull → build → app·celery_worker 재생성 → alembic
                        → nginx -t & reload → celery_beat 재생성·기동 확인)
   │
   ▼
[워크플로가 라이브 검증]  /health 200·database:connected · bideasy.kr 200 · sitemap.xml 200
```

**왜 forced command 인가**: 배포 키를 GitHub Secrets 에 넣는다는 건 "그 시크릿을 읽을 수 있는 사람은 프로덕션 셸을 얻는다"와 같다. forced command 를 걸면 그 키로 할 수 있는 일이 위 4개 액션으로 고정되므로, 키가 새더라도 임의 명령 실행·파일 유출로 이어지지 않는다.

---

## 1. 사전 조건 (확인 필요)

- **Lightsail 방화벽 22번 포트**: GitHub Actions 러너는 IP 가 매번 바뀐다. 현재 SSH 가 특정 IP 로만 열려 있다면 러너가 접속하지 못한다.
  - 권장: 22번을 열어두되 **비밀번호 로그인 금지(키 전용)** + 이 문서의 forced command 조합으로 위험을 줄인다. (`PasswordAuthentication no` 확인)
  - 더 조이고 싶으면 `https://api.github.com/meta` 의 `actions` IP 대역만 허용 — 단 대역이 자주 바뀌어 유지비가 든다.
- 서버에 `~/Bideasy` 레포와 `infra/.env.production` 이 이미 있고 `./deploy.sh deploy` 가 손으로는 동작하는 상태.

---

## 2. 서버 1회 설정 (사용자 작업, 5~10분)

### 2-1. 배포 전용 키 생성 (로컬 PC에서)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/bideasy_deploy_ci -C "deploy@github-actions" -N ""
```
> 개인 계정 키를 재사용하지 말 것. 이 키는 forced command 로 묶인 배포 전용이다.

### 2-2. 에이전트 스크립트 설치 (서버에서)

```bash
cd ~/Bideasy && git pull origin master
cp infra/deploy-agent.sh ~/deploy-agent.sh
chmod 755 ~/deploy-agent.sh
```
> **에이전트를 고쳤을 때는 서버에서 위 `cp` 를 다시 실행해야 한다**(배포는 에이전트를 갱신하지 않는다 — 그게 이 설계의 요점). 저장소 상태와 무관하게 받으려면:
> ```bash
> curl -fsSL https://raw.githubusercontent.com/hosicompany/Bideasy/master/infra/deploy-agent.sh -o ~/deploy-agent.sh && chmod 755 ~/deploy-agent.sh && sha256sum ~/deploy-agent.sh
> ```
>
> **레포 안 경로를 직접 forced command 로 걸지 말 것.** 배포가 곧 `git pull` 이므로, 레포 안을 가리키면 코드 변경이 화이트리스트 자체를 바꿀 수 있다. 레포 밖(`~/deploy-agent.sh`)에 복사해서 고정한다. 에이전트를 수정하고 싶을 때만 위 `cp` 를 다시 실행.

### 2-3. 공개키를 forced command 로 등록 (서버에서)

`~/.ssh/authorized_keys` 에 **한 줄**로 추가. `AAAA...` 자리에 2-1 에서 만든 `~/.ssh/bideasy_deploy_ci.pub` 내용을 넣는다.

```
command="/home/ubuntu/deploy-agent.sh",no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc,no-X11-forwarding ssh-ed25519 AAAA...실제공개키... deploy@github-actions
```

확인:
```bash
# 로컬에서 — 허용 액션은 통과, 임의 명령은 거부되어야 한다
ssh -i ~/.ssh/bideasy_deploy_ci ubuntu@43.203.66.120 status      # OK
ssh -i ~/.ssh/bideasy_deploy_ci ubuntu@43.203.66.120 'cat ~/Bideasy/infra/.env.production'   # denied 여야 정상
```

---

## 3. GitHub Secrets 등록 (사용자 작업)

리포지토리 → **Settings → Secrets and variables → Actions → New repository secret**

| 이름 | 값 |
|---|---|
| `DEPLOY_HOST` | `43.203.66.120` |
| `DEPLOY_USER` | `ubuntu` |
| `DEPLOY_SSH_KEY` | `~/.ssh/bideasy_deploy_ci` **개인키 전문**(`-----BEGIN…END…-----` 포함, 줄바꿈 그대로) |
| `DEPLOY_KNOWN_HOSTS` | 아래 한 줄 |

```
43.203.66.120 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPOIehGVT4T5J+7chcFuu2/hZdhVu0AIbUHqWrj44Fov
```

> 이 호스트키는 2026-08-08 새 인스턴스 전환 때 확인해 등록한 값이며 지문은 `SHA256:e1QMNImP/O7GluKo9T3fB0zFiJBmPEHXM0PRtnWzELs` 이다. 서버 콘솔에서 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 로 **한 번 대조**한 뒤 등록하는 것을 권한다(중간자 공격 방지의 유일한 지점).

### (선택) 승인 게이트
**Settings → Environments → New environment → `production`** 을 만들고 *Required reviewers* 에 본인을 넣으면, 버튼을 눌러도 승인 클릭 전까지 배포가 대기한다. 워크플로는 이미 `environment: production` 을 쓰므로 환경만 만들면 적용된다.

---

## 4. 사용법

**Actions → Deploy (production) → Run workflow** (입력값 없음)

> **celery_beat 수동 재생성은 더 이상 필요 없다.** PR #39·#40 이후 `deploy.sh deploy` 가 매번 `celery_beat` 를 force-recreate 하고, 기동에 실패하면 배포를 실패로 끝낸다. CLAUDE.md 함정목록 #3("deploy.sh 가 celery_beat 재생성 안 함")은 그 시점부터 사실이 아니다 — 이 PR 에서 함께 정정했다.

동작:
1. master 최신 커밋을 찍고, 그 커밋의 CI `test`·`build` 가 **success** 인지 확인 — 아니면 배포하지 않고 실패한다(우회 옵션 없음). `lint`·`flutter` 는 게이트에서 제외.
2. 배포 실행.
3. 라이브 검증(`/health` 의 `status:ok`·`database:connected`, `bideasy.kr` 200, `sitemap.xml` 200). 하나라도 어긋나면 잡이 빨갛게 끝난다.
4. 요약(커밋·beat 재생성 여부·health 응답)이 실행 화면 Summary 에 남는다.

---

## 5. 실패했을 때

| 증상 | 원인·대처 |
|---|---|
| `CI 잡 'test' 미통과` | 배포 전 게이트가 막은 것. CI 를 고치고 다시 실행. |
| `Permission denied (publickey)` | 2-3 등록 누락/오타, 또는 `DEPLOY_SSH_KEY` 개행 깨짐. |
| `Host key verification failed` | `DEPLOY_KNOWN_HOSTS` 불일치. 서버 재생성 등으로 호스트키가 바뀌었는지 확인(바뀐 게 정상이면 값 갱신). |
| SSH 연결 타임아웃 | Lightsail 방화벽이 러너 IP 를 막는 중(§1). |
| `denied: 이 키는 배포 전용입니다` | 워크플로가 화이트리스트 밖 액션을 보냈다는 뜻. `~/deploy-agent.sh` 버전이 오래됐을 수 있음 → 2-2 재실행. |
| 배포는 됐는데 Verify 실패 | 앱이 안 뜬 것. **직접 SSH 로 들어가** `./deploy.sh logs app` 확인 후 필요 시 `./deploy.sh rollback`. |

**롤백은 자동화하지 않았다.** 롤백은 상황 판단이 필요한 작업이라 사람이 SSH 로 들어가 `./deploy.sh rollback` 을 실행한다(개인 키 사용, 배포 키로는 불가).

**키 폐기**: 배포 키가 샜다고 판단되면 서버 `~/.ssh/authorized_keys` 에서 해당 한 줄만 지우면 즉시 무효화된다(다른 접속 경로에 영향 없음).

---

## 6. 이 자동화가 대체하지 않는 것

- **`.env.production` 변경** — 서버에만 있는 파일이라 손으로 편집해야 한다(예: `CONTENT_LLM_API_KEY` 추가).
- **`BILLING_ENC_KEY` 등 비밀값 관리** — 자동화 대상 아님. 변경 금지 항목은 CLAUDE.md 함정목록 참조.
- **최초 볼륨 권한(`chown 10001`)·SSL 발급** — `deploy.sh init`/`ssl-init` 계열, 사람이 판단해서 실행.
- **사이트맵 재제출 같은 외부 콘솔 작업.**
