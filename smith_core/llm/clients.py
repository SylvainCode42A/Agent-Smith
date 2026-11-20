import time
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI, NOT_GIVEN

from smith_core.llm.keys import KeyRing, provider_prefix

load_dotenv()

MAX_RETRIES = 3          # other retryable errors (5xx, connection...)
TIMEOUT_S = 60.0
MAX_BACKOFF_S = 8        # cap of one wait for the other errors
MAX_429_WAIT_S = 30      # cap of one wait after a 429 (rate limit)
# Default total time we accept to wait on 429s during one chat() call.
# Kept short for MBPP (100 s budget); SWE-bench passes a bigger value.
DEFAULT_RATE_LIMIT_BUDGET_S = 15.0


def retry_after_s(error: APIStatusError) -> float | None:
    """Seconds asked by the provider in the Retry-After header, if any."""
    try:
        value = error.response.headers.get("retry-after")
        return float(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


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
    def __init__(self, base_url: str, model: str,
                 rate_limit_budget_s: float = DEFAULT_RATE_LIMIT_BUDGET_S
                 ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.rate_limit_budget_s = rate_limit_budget_s
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
        other_retries = 0
        waited_429 = 0.0
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
                             status >= 500 or
                             (status == 400 and isinstance(error.body, dict)
                              and error.body.get("code") == "tool_use_failed"))
                if not retryable:
                    raise
                if status == 429:
                    # Rate limit: wait as long as the provider asks (or
                    # exponential), within the budget given to the client.
                    wait = retry_after_s(error) or 2 ** (retries + 1)
                    wait = min(wait, MAX_429_WAIT_S)
                    if waited_429 + wait > self.rate_limit_budget_s:
                        raise
                    waited_429 += wait
                else:
                    if other_retries >= MAX_RETRIES:
                        raise
                    other_retries += 1
                    wait = min(2 ** other_retries, MAX_BACKOFF_S)
                retries += 1
                self.client = self.client.with_options(
                    api_key=self.keyring.rotate())
                time.sleep(wait)

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
