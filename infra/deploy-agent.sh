#!/usr/bin/env bash
# 배포 전용 SSH forced-command 에이전트.
#
# 서버 ~/.ssh/authorized_keys 에 이 스크립트를 forced command 로 걸어 두면,
# 해당 키로 접속한 쪽은 아래 화이트리스트 명령만 실행할 수 있고 임의 셸은 못 연다.
#   command="/home/ubuntu/deploy-agent.sh",no-agent-forwarding,no-port-forwarding,no-pty,no-X11-forwarding ssh-ed25519 AAAA... deploy@github-actions
#
# 설치·운영 절차: docs/DEPLOY_CD.md
# ⚠️ 이 파일은 레포에 있지만, 서버에는 **레포 밖 경로(~/deploy-agent.sh)로 복사해** 쓴다.
#    레포 안 경로를 직접 가리키면 배포(git pull)가 화이트리스트 자체를 바꿀 수 있다.
set -euo pipefail

INFRA_DIR="${BIDEASY_INFRA_DIR:-$HOME/Bideasy/infra}"
LOG_FILE="${BIDEASY_DEPLOY_LOG:-$HOME/deploy-agent.log}"
COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.production"
PROJECT_NAME="infra"

action="${SSH_ORIGINAL_COMMAND:-}"
# 인자 없는 단일 토큰만 허용 — 공백·세미콜론 등이 섞이면 즉시 거부.
case "$action" in
  *[!a-z-]*|"") action="__invalid__" ;;
esac

log() {
  local _client="${SSH_CLIENT:-unknown}"
  printf '%s | from=%s action=%s | %s\n' \
    "$(date -Is)" "${_client%% *}" "${SSH_ORIGINAL_COMMAND:-<none>}" "$1" >> "$LOG_FILE"
}

dc() {
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$PROJECT_NAME" "$@"
}

cd "$INFRA_DIR"

case "$action" in
  deploy)
    log "start deploy"
    ./deploy.sh deploy
    log "done deploy"
    ;;

  indexnow-backfill)
    # 지금 살아있는 URL 을 검색엔진에 일괄 통보(일회성). 평소엔 발행·수집 훅이 자동 처리.
    log "indexnow-backfill"
    dc exec -T app python scripts/indexnow_backfill.py
    ;;

  status)
    log "status"
    ./deploy.sh status
    ;;

  health)
    log "health"
    dc exec -T app curl -sf http://localhost:8000/health
    ;;

  *)
    log "DENIED"
    echo "denied: 이 키는 배포 전용입니다. 허용 액션: deploy | indexnow-backfill | status | health" >&2
    exit 1
    ;;
esac
