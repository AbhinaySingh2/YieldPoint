import asyncio
from google import genai
import os
from dotenv import load_dotenv

load_dotenv()

async def run():
    client = genai.Client()
    print("Testing gemini-3.6-flash...")
    try:
        response = await client.aio.models.generate_content(
            model='gemini-3.6-flash',
            contents='test'
        )
        print("Success:", response.text)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(run())
