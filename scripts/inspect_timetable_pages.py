"""Inspect pages 2, 3, 4 of 3rd sem timetable using Gemini Vision."""
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

load_dotenv()

key = os.environ.get("GEMINI_API_KEY")
if not key:
    sys.exit("GEMINI_API_KEY is not set.")

client = genai.Client(api_key=key)

for page_num in range(3, 5):
    img_path = f"scripts/page_{page_num}.png"
    if not os.path.exists(img_path):
        continue
    
    img = Image.open(img_path)
    prompt = (
        "Briefly summarize what this page contains. Identify:\n"
        "1. Document Title / Header\n"
        "2. Table Type: Is it Course/Subject Lookup Table, or Faculty Lookup Table?\n"
        "3. Columns present in the table.\n"
        "4. List the first 5 rows/entries as samples."
    )
    
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=[img, prompt],
            )
            print(f"=== PAGE {page_num} SUMMARY ===")
            print(response.text)
            print("-" * 50)
            break
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
            time.sleep(3)
    time.sleep(2)

