import time
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI, NOT_GIVEN

from smith_core.llm.keys import KeyRing, provider_prefix

load_dotenv()

MAX_RETRIES = 3
TIMEOUT_S = 60.0


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    request_time_ms: float
    retries: int
    api_url: str
    model_name: str


class LLMClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.keyring = KeyRing(provider_prefix(base_url))

        self.client = OpenAI(
            api_key=self.keyring.current(),
            base_url=self.base_url,
            max_retries=0,
            timeout=TIMEOUT_S,
        )

    def chat(self, messages: list[dict], max_tokens: int = 1024,
             stop: list[str] | None = None) -> LLMResponse:

        """ Sends a chat request to the language model and returns
            the response.
            Args:
                messages (list[dict]): A list of message dictionaries
                    representing the conversation history.
                    Each dictionary should contain keys like "role"
                    (e.g., "user", "assistant") and "content".
                max_tokens (int, optional): The maximum number of tokens to
                    generate in the response. Defaults to 1024.
                stop (list[str] | None, optional): A list of stop sequences
                    to end the generation early. Defaults to None.
            Returns:
                LLMResponse: An object containing the generated text,
                    token usage, request time, and other metadata.
            Raises:
                APIStatusError: If the API returns a non-retryable status code.
                APIConnectionError: If there is a connection issue
                    with the API.`
            """

        retries = 0
        start = time.perf_counter()
        while True:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    stop=stop or NOT_GIVEN,
                )
                break
            except (APIStatusError, APIConnectionError) as error:
                status = getattr(error, "status_code", None)

                retryable = (status is None or status == 429 or
                             status >= 500)
                if not retryable or retries >= MAX_RETRIES:
                    raise
                retries += 1
                self.client = self.client.with_options(
                    api_key=self.keyring.rotate())
                time.sleep(min(2 ** retries, 8))

        usage = response.usage
        return LLMResponse(
            text=response.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            request_time_ms=(time.perf_counter() - start) * 1000,
            retries=retries,
            api_url=f"{self.base_url}",
            model_name=self.model,
        )
