import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from app.api.v1.endpoints.analysis import AttachmentDownloader
from app.core.config import settings

async def test_logic():
    bid_id = "R25BK01253548-000"
    print(f"Testing AttachmentDownloader logic for {bid_id}...")
    
    attachments = await AttachmentDownloader.get_attachment_list(bid_id, settings.PUBLIC_DATA_KEY)
    
    print(f"Result count: {len(attachments)}")
    for att in attachments:
        print(f" - {att.get('atchFileNm')} : {att.get('atchFileUrl')}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_logic())
