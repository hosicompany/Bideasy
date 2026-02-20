from app.core.celery_app import celery_app
from app.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, max_retries=3)
def crawl_notices(self, contract_type: str = "CONSTRUCTION", pages: int = 3):
    """Background task to crawl bid notices from public API."""
    from app.db.session import SessionLocal
    from app.services.crawler import CrawlerService

    logger.info(f"Crawl task started: type={contract_type}, pages={pages}")
    db = SessionLocal()
    try:
        crawler = CrawlerService()
        notices = crawler.fetch_notices(
            page=1,
            per_page=10 * pages,
            contract_type=contract_type,
        )
        logger.info(f"Crawl complete: {len(notices)} notices fetched")
        return {"fetched": len(notices)}
    except Exception as e:
        logger.error(f"Crawl task failed: {e}")
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()
