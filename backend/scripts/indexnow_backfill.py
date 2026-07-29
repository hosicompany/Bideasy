"""IndexNow 일괄 통보 — 지금 살아있는 URL 을 한 번에 알린다(일회성).

색인 구조를 바꾼 직후처럼 "이미 있는 URL 을 다시 알려야 하는" 상황에서 쓴다.
평소에는 발행·수집 훅이 자동으로 처리하므로 이 스크립트를 돌릴 일이 없다.

실행(서버 컨테이너 안):
    docker compose -f docker-compose.prod.yml --env-file .env.production -p infra \
      exec app python scripts/indexnow_backfill.py

옵션:
    --limit N   공고 URL 상한 (기본: 서비스 상한 MAX_PER_RUN)
    --dry-run   실제 발송 없이 대상만 출력
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import models  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services import blog as blog_svc  # noqa: E402
from app.services import indexnow  # noqa: E402

STATIC_PATHS = ["", "/search", "/calculator", "/guide", "/pricing", "/blog", "/diagnose"]


def _now_kst_naive() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).replace(tzinfo=None)


def collect(db, limit: int | None) -> list[str]:
    urls = [f"{indexnow.SITE_URL}{p}" for p in STATIC_PATHS]
    urls += indexnow.blog_urls([p["slug"] for p in blog_svc.list_posts(db)])

    q = (
        db.query(models.Notice.bid_no)
        .filter(
            models.Notice.start_date.isnot(None),
            models.Notice.end_date.isnot(None),
            models.Notice.end_date > _now_kst_naive(),
        )
        .order_by(models.Notice.bid_no.desc())
    )
    if limit:
        q = q.limit(limit)
    urls += indexnow.notice_urls([row[0] for row in q.all()])
    return urls


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="공고 URL 상한")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        urls = collect(db, args.limit)
        # 일회성 일괄 통보는 "전량 발송"이 목적이므로 자동 훅용 상한(MAX_PER_RUN)을
        # 명시적으로 올린다. 프로토콜 상한(10,000/POST)은 submit 이 알아서 분할한다.
        print(f"대상 URL {len(urls)}건 — 전량 발송")
        print("  예시:", *urls[:3], sep="\n    ")
        if args.dry_run:
            print("dry-run — 발송하지 않음")
            return 0
        if not indexnow.is_enabled():
            print("발송 비활성(APP_ENV != production 이거나 INDEXNOW_KEY 미설정) — 중단")
            return 1
        result = indexnow.submit(urls, reason="backfill", max_urls=len(urls))
        print("결과:", result)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
