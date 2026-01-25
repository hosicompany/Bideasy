import sys
import os

# Ensure backend is in path
current_dir = os.getcwd()
if current_dir.endswith('backend'):
    sys.path.append(current_dir)
else:
    sys.path.append(os.path.join(current_dir, 'backend'))

from app.core.config import settings
from app.services.crawler import CrawlerService

print(f"Loading settings. API Key present: {bool(settings.PUBLIC_DATA_KEY)}")
if settings.PUBLIC_DATA_KEY:
    print(f"API Key start: {settings.PUBLIC_DATA_KEY[:5]}...")

print("Starting Crawler Verification...")
try:
    # We want to see the error print from the service, which acts on stdout.
    # But we also capture the return.
    results = CrawlerService.fetch_notices(size=10)
    print("--------------------------------------------------")
    print(f"Final Result Count: {len(results)}")
    if results:
        print(f"First Item Title: {results[0].get('title')}")
        print(f"First Item BidNo: {results[0].get('bid_no')}")
except Exception as e:
    print(f"Script Error: {e}")
