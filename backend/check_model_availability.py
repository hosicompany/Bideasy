from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), 'app', '.env'))

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    # Try finding .env in project root if not found in app
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
    api_key = os.getenv("OPENAI_API_KEY")

print(f"API Key loaded: {'Yes' if api_key else 'No'}")

client = OpenAI(api_key=api_key)

print("\n--- Checking for gpt-5-nano availability ---")
try:
    # Try to list models and find gpt-5-nano
    models = client.models.list()
    gpt5_models = [m.id for m in models.data if 'gpt-5' in m.id]
    
    if gpt5_models:
        print(f"Found GPT-5 related models: {gpt5_models}")
    else:
        print("No specific 'gpt-5' models found in the list.")

    # Try a direct test call just in case it's available but not listed (rare but possible for betas) 
    # or if the user wants to force try it.
    target_model = "gpt-5-nano"
    print(f"\nAttempting simple completion with '{target_model}'...")
    
    response = client.chat.completions.create(
        model=target_model,
        messages=[
            {"role": "user", "content": "Hello, are you gpt-5-nano?"}
        ],
        max_tokens=10
    )
    print(f"SUCCESS: Model {target_model} worked!")
    print(f"Response: {response.choices[0].message.content}")

except Exception as e:
    print(f"FAILED: Could not use {target_model} or list models.")
    print(f"Error: {e}")
