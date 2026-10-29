"""Step 1: does the Gemini key + model work at all?

Run from the project folder:
    python scripts/llm_check_basic.py            # one tiny request
    python scripts/llm_check_basic.py --list     # print model IDs your key can use

Reads GEMINI_API_KEY and LLM_MODEL from .env. Never prints the key.
"""
import os
import sys

from dotenv import load_dotenv
from google import genai

load_dotenv()

key = os.environ.get("GEMINI_API_KEY")
if not key:
    sys.exit("GEMINI_API_KEY is not set. Add it to .env (one line, no quotes) and run again.")

client = genai.Client(api_key=key)

if "--list" in sys.argv:
    for m in client.models.list():
        print(m.name)
    sys.exit(0)

model = os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite")
print(f"Using model: {model}")
response = client.models.generate_content(model=model, contents="Reply with exactly: OK")
print("Reply:", (response.text or "").strip())
