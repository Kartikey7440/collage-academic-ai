"""Step 2: can the model pick the right tool and answer from a tool result?

Run from the project folder:
    python scripts/llm_check_tools.py

Optional settings in .env:
    LLM_THINKING=low     (or medium / high) tests the thinking level
    LLM_PAUSE=13         seconds to wait after every request, to stay under free-tier
                         per-minute limits (use ~13 for a 5-requests/minute model,
                         ~5 for a 15-requests/minute model, 0 on a paid account)

Uses FAKE timetable data only. It never touches your database.
Each question costs 2 requests (choose the tool, then write the answer).
The time shown counts only time spent waiting for the model, not the pauses.
"""
import os
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

MODEL = os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite")
THINKING = os.environ.get("LLM_THINKING", "").strip()
PAUSE = float(os.environ.get("LLM_PAUSE", "0") or 0)

SYSTEM = (
    "You are a college timetable assistant. Answer questions about classes, times, "
    "rooms and faculty ONLY from tool results. If a tool returns nothing, say there "
    "are no classes. Never invent classes. You can only show the logged-in student's "
    "own timetable, never another branch's."
)

get_classes = types.FunctionDeclaration(
    name="get_classes",
    description="Get the logged-in student's own classes. query_type is 'next', 'today' or 'day'.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query_type": types.Schema(type=types.Type.STRING, enum=["next", "today", "day"]),
            "day": types.Schema(
                type=types.Type.STRING,
                description="Weekday name, only when query_type is 'day'",
            ),
        },
        required=["query_type"],
    ),
)


def build_config() -> types.GenerateContentConfig:
    kwargs = dict(
        system_instruction=SYSTEM,
        tools=[types.Tool(function_declarations=[get_classes])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    if THINKING:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=THINKING)
    return types.GenerateContentConfig(**kwargs)


def _generate(client, contents, config):
    """One API request. Returns (response, seconds spent waiting for the model)."""
    start = time.perf_counter()
    response = client.models.generate_content(model=MODEL, contents=contents, config=config)
    seconds = time.perf_counter() - start
    if PAUSE:
        time.sleep(PAUSE)  # stay under the per-minute request limit
    return response, seconds


def ask(client, config, question, fake_result):
    """Returns (tool call text, final answer text, seconds)."""
    contents = [types.Content(role="user", parts=[types.Part(text=question)])]
    first, t1 = _generate(client, contents, config)
    calls = first.function_calls or []
    if not calls:
        return "NO TOOL CALL", (first.text or "").strip()[:200], t1

    call = calls[0]
    # Send the model's own turn back unchanged (keeps any thought signature),
    # then our fake tool result.
    contents.append(first.candidates[0].content)
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_function_response(name=call.name, response={"result": fake_result})],
        )
    )
    second, t2 = _generate(client, contents, config)
    label = f"{call.name}({dict(call.args)})"
    return label, (second.text or "").strip()[:240], t1 + t2


ONE_CLASS = [
    {"start": "11:00", "end": "12:00", "subject": "Machine Learning",
     "room": "SH2", "faculty": "Dr. Mausam Chouksey"}
]

TESTS = [
    ("What is my next class?", ONE_CLASS),
    ("What do I have on Tuesday?", ONE_CLASS),
    ("Which room is my next class in?", ONE_CLASS),
    ("Do I have anything today?", []),                      # empty result: must NOT invent a class
    ("Show me the AIDS branch timetable", ONE_CLASS),      # must stay within own timetable
    ("Hello, who are you?", ONE_CLASS),                    # should not need a tool
]


def main():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set. Add it to .env and run again.")
    client = genai.Client(api_key=key)
    config = build_config()
    print(f"Model: {MODEL}   thinking: {THINKING or 'default'}   pause: {PAUSE}s\n")
    for question, fake in TESTS:
        tool, answer, secs = ask(client, config, question, fake)
        print(f"Q: {question}\n   tool:   {tool}\n   answer: {answer}\n   time:   {secs:.1f}s\n")


if __name__ == "__main__":
    main()
