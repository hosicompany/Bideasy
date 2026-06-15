#!/bin/bash
# BidEasy Production Deployment Script
# Usage: ./deploy.sh [init|deploy|ssl-init|logs|status|rollback]

set -euo pipefail

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.production"
# 실제 운영 인스턴스가 -p infra (디렉터리명 기본값) 로 떠있어서 일치시킴.
# 옛 deploy.sh 가 PROJECT_NAME=bideasy 였으나 실 서버 컨테이너 라벨과 안 맞아
# `up -d` 시 새 컨테이너를 만들려고 시도하다 이름 충돌 발생.
PROJECT_NAME="infra"
DOMAIN="bideasy.kr"
EMAIL="support@bideasy.kr"

cd "$(dirname "$0")"

# Helper: run docker compose with consistent flags
dc() {
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$PROJECT_NAME" "$@"
}

case "${1:-deploy}" in

  init)
    echo "=== BidEasy Initial Setup ==="

    # Check .env.production exists
    if [ ! -f .env.production ]; then
      echo "ERROR: .env.production not found."
      echo "Copy .env.production.example to .env.production and fill in values."
      exit 1
    fi

    # Build and start services
    dc up -d --build

    # Run database migrations
    echo "Running database migrations..."
    dc \
      exec app alembic upgrade head

    echo "=== Init complete. Run './deploy.sh ssl-init' to set up HTTPS. ==="
    ;;

  ssl-init)
    echo "=== Issuing SSL Certificate ==="

    # Get certificate using webroot challenge (nginx stays running for HTTP)
    # --entrypoint "" overrides the renewal-loop entrypoint in docker-compose
    dc run --rm --entrypoint "" certbot \
      certbot certonly --webroot -w /var/www/certbot \
      --email "$EMAIL" --agree-tos --no-eff-email \
      -d "$DOMAIN" -d "www.$DOMAIN"

    # Switch nginx to SSL config
    echo "Switching nginx to SSL config..."
    sed -i 's|NGINX_CONF_DIR=.*|NGINX_CONF_DIR=./nginx/conf.d|' "$ENV_FILE"

    # Restart nginx with SSL
    dc up -d --force-recreate nginx

    echo "=== SSL setup complete ==="
    ;;

  ssl-init-api)
    echo "=== Issuing SSL Certificate for api.$DOMAIN ==="

    # api.bideasy.kr 전용 인증서 발급.
    # 사전 조건: nginx 가 이미 실행 중이고 conf.d/default.conf 의 HTTP server_name 에
    # api.$DOMAIN 이 포함되어 있어야 함 (ACME challenge 응답 위해).
    dc run --rm --entrypoint "" certbot \
      certbot certonly --webroot -w /var/www/certbot \
      --email "$EMAIL" --agree-tos --no-eff-email \
      -d "api.$DOMAIN"

    # 발급 성공 시 api.bideasy.kr.conf 활성화 (.disabled → .conf)
    if [ -f ./nginx/conf.d/api.bideasy.kr.conf.disabled ]; then
      echo "Activating nginx config for api.$DOMAIN..."
      mv ./nginx/conf.d/api.bideasy.kr.conf.disabled \
         ./nginx/conf.d/api.bideasy.kr.conf
      dc restart nginx
    else
      echo "WARN: ./nginx/conf.d/api.bideasy.kr.conf.disabled 없음 — 수동 활성화 필요"
    fi

    echo "=== api SSL setup complete: https://api.$DOMAIN/health 로 확인 ==="
    ;;

  deploy)
    echo "=== Deploying BidEasy ==="

    # Pull latest code
    cd ..
    git pull origin master
    cd infra

    # Build new images
    dc build app celery_worker

    # Rolling restart: app first, then celery
    dc up -d --no-deps app
    echo "Waiting for app health check..."
    sleep 10

    # Verify health
    if dc \
      exec app curl -sf http://localhost:8000/health > /dev/null 2>&1; then
      echo "App is healthy."
    else
      echo "WARNING: Health check failed. Check logs with './deploy.sh logs app'"
    fi

    # Update celery worker
    dc up -d --no-deps celery_worker

    # Run migrations
    dc \
      exec app alembic upgrade head

    # Reload nginx to apply conf.d changes (routing/redirects).
    # git pull 이 mount된 conf 를 갱신해도 nginx 는 reload 해야 적용됨.
    # nginx -t 통과할 때만 reload (잘못된 설정으로 죽는 것 방지).
    echo "Reloading nginx config..."
    if dc exec -T nginx nginx -t; then
      dc exec -T nginx nginx -s reload
      echo "nginx reloaded."
    else
      echo "WARNING: nginx config test FAILED — reload 건너뜀. ./nginx/conf.d 확인 후 수동 reload 필요."
    fi

    echo "=== Deploy complete ==="
    ;;

  logs)
    SERVICE="${2:-app}"
    dc logs -f --tail=100 "$SERVICE"
    ;;

  status)
    echo "=== Service Status ==="
    dc ps
    echo ""
    echo "=== Health Check ==="
    dc \
      exec app curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "Health check unavailable"
    ;;

  rollback)
    echo "=== Rolling Back ==="
    cd ..
    PREV_COMMIT=$(git log --oneline -2 | tail -1 | awk '{print $1}')
    echo "Rolling back to: $PREV_COMMIT"
    git checkout "$PREV_COMMIT"
    cd infra
    dc up -d --build app celery_worker
    echo "=== Rollback complete. Run migrations manually if needed. ==="
    ;;

  backup)
    echo "=== Database Backup ==="
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="backup_${TIMESTAMP}.sql.gz"
    dc \
      exec -T db pg_dump -U "${POSTGRES_USER:-bideasy}" "${POSTGRES_DB:-bideasy_db}" \
      | gzip > "$BACKUP_FILE"
    echo "Backup saved: $BACKUP_FILE"
    ;;

  *)
    echo "Usage: $0 {init|deploy|ssl-init|ssl-init-api|logs|status|rollback|backup}"
    echo ""
    echo "Commands:"
    echo "  init          - First-time setup (build, start, migrate)"
    echo "  deploy        - Pull latest code, rebuild, rolling restart"
    echo "  ssl-init      - Issue Let's Encrypt SSL for bideasy.kr + www"
    echo "  ssl-init-api  - Issue Let's Encrypt SSL for api.bideasy.kr + activate api conf"
    echo "  logs          - Tail service logs (default: app)"
    echo "  status        - Show service status and health"
    echo "  rollback      - Revert to previous git commit"
    echo "  backup        - Dump PostgreSQL database"
    exit 1
    ;;
esac
