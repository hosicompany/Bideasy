from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'app', '.env'))
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
    api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=api_key)

print("\n--- Listing available GPT models ---")
try:
    models = client.models.list()
    gpt_models = [m.id for m in models.data if 'gpt' in m.id]
    for m in sorted(gpt_models):
        print(m)
        
except Exception as e:
    print(f"Error listing models: {e}")
