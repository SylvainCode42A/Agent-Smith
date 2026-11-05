import os
import time

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError

load_dotenv()

client = OpenAI(
    api_key=os.environ["GEMINI_API_KEY"],
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    max_retries=0,
    timeout=60,
)

# Un appel, avec stop + réflexion réduite
start = time.perf_counter()
try:
    response = client.chat.completions.create(
        model="gemini-3.5-flash-lite",
        messages=[{"role": "user", "content": "Compte de 1 à 10,"
                   "un nombre par ligne"}],
        stop=["5"],
        reasoning_effort="low",
    )
except APIStatusError as error:
    print(error.body)
    raise

end = time.perf_counter()
time_in_ms = (end - start) * 1000

print(response.choices[0].message.content)
print(response.usage)
print(f"{time_in_ms:.0f} ms")
