import sys
from dataclasses import asdict
from openai import APIStatusError

from smith_core.llm.clients import LLMClient

url, model = sys.argv[1], sys.argv[2]
client = LLMClient(url, model)
try:
    response = client.chat([{"role": "user", "content": "Dis bonjour"}],
                           max_tokens=50)
except APIStatusError as error:
    print(error.status_code, error.body)
    raise

for name, value in asdict(response).items():
    print(f"{name:16} {value}")
