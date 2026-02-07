import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from app.api.v1.endpoints.analysis import AttachmentDownloader
from app.core.config import settings

async def list_files():
    bid_id = "R25BK01255891-001" 
    print(f"Listing attachments for {bid_id}...")
    
    attachments = await AttachmentDownloader.get_attachment_list(bid_id, settings.PUBLIC_DATA_KEY)
    
    print(f"Found {len(attachments)} files:")
    for att in attachments:
        print(f" - Name: {att.get('atchFileNm')}")
        print(f"   URL: {att.get('atchFileUrl')}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(list_files())
