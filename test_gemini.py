"""Smoke-test the Gemini model used by agent.py."""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

MODEL = "gemini-3.5-flash-lite"


async def run() -> None:
    # Prefer the same google-genai client path when available; fall back gracefully.
    try:
        from google import genai

        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        print(f"Testing {MODEL} via google.genai...")
        response = await client.aio.models.generate_content(
            model=MODEL,
            contents="Reply with the single word: ok",
        )
        print("Success:", getattr(response, "text", response))
        return
    except Exception as primary:
        print("google.genai path failed:", primary)

    try:
        import google.generativeai as genai_legacy

        genai_legacy.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        model = genai_legacy.GenerativeModel(MODEL)
        print(f"Testing {MODEL} via google.generativeai...")
        response = await model.generate_content_async(
            "Reply with the single word: ok"
        )
        print("Success:", response.text)
    except Exception as secondary:
        print("Error:", secondary)


if __name__ == "__main__":
    asyncio.run(run())
