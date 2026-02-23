#!/bin/bash
# BidEasy Production Deployment Script
# Usage: ./deploy.sh [init|deploy|ssl-init|logs|status|rollback]

set -euo pipefail

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.production"
PROJECT_NAME="bideasy"
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
    dc run --rm certbot \
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
    echo "Usage: $0 {init|deploy|ssl-init|logs|status|rollback|backup}"
    echo ""
    echo "Commands:"
    echo "  init      - First-time setup (build, start, migrate)"
    echo "  deploy    - Pull latest code, rebuild, rolling restart"
    echo "  ssl-init  - Issue Let's Encrypt SSL certificate"
    echo "  logs      - Tail service logs (default: app)"
    echo "  status    - Show service status and health"
    echo "  rollback  - Revert to previous git commit"
    echo "  backup    - Dump PostgreSQL database"
    exit 1
    ;;
esac
