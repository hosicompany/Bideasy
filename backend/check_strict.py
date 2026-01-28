from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'app', '.env'))
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
    api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=api_key)

try:
    print("Fetching model list...")
    models = client.models.list()
    
    # Check for exact match
    target = "gpt-5-nano"
    found = any(m.id == target for m in models.data)
    
    # Also check for any gpt-5
    gpt5_variants = [m.id for m in models.data if "gpt-5" in m.id]
    
    if found:
        print(f"RESULT: AVAILABLE ({target})")
    elif gpt5_variants:
        print(f"RESULT: VARIANTS FOUND ({', '.join(gpt5_variants)})")
    else:
        print("RESULT: UNAVAILABLE")
        
except Exception as e:
    print(f"RESULT: ERROR ({e})")
