import sys
from smith_core.agent.loop import Limits, run_agent
from smith_core.llm.clients import LLMClient, LLMResponse
from smith_core.models import SandboxConfig
from smith_core.sandbox.fake import FakeSandbox


class FakeLLM:
    """Always answers with code that never calls final_answer."""

    def chat(self, messages, max_tokens=1024, stop=None):
        return LLMResponse(text="Thought:\n```python\nprint(2+2)\n```",
                           input_tokens=10, output_tokens=10,
                           request_time_ms=0, retries=0,
                           api_url="fake", model_name="fake")


class ScriptedLLM:
    """Returns the given texts in order and records the messages it got."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    def chat(self, messages, max_tokens=1024, stop=None):
        self.calls.append([dict(m) for m in messages])
        text = self.texts[len(self.calls) - 1]
        return LLMResponse(text=text, input_tokens=10, output_tokens=10,
                           request_time_ms=0, retries=0,
                           api_url="fake", model_name="fake")


SYSTEM = (
    "You solve tasks by writing Python.\n"
    "Answer with 'Thought:' then ONE ```python block ending with <end_code>.\n"
    "Write, test and submit in the SAME block: define the function, run a "
    "quick assert, then call final_answer.\n"
    "Call final_answer with the function's source code written as a string "
    "literal (triple quotes). Never use inspect: it does not work here.\n"
)
USER = ("Write a function add(a, b) that adds two numbers, test it, "
        "then call final_answer with the function's source code as a string.")


def report(title, expectation, out):
    """Print a readable summary of one run_agent call."""
    print("=" * 64)
    print(f"SCENARIO : {title}")
    print(f"ATTENDU  : {expectation}")
    print("-" * 64)
    for st in out.steps:
        code = st.sandbox_input.strip().replace("\n", " | ") or "(no code)"
        print(f"  tour {st.step}")
        print(f"    code execute : {code[:70]}")
        print(f"    sortie       : {st.sandbox_output.strip() or '(vide)'}")
    print("-" * 64)
    print(f"  success    = {out.success}")
    print(f"  iterations = {out.iterations}")
    print(f"  error      = {out.error}")
    print(f"  solution   = {out.solution!r}")


# --- failure path (no network): the LLM never calls final_answer ---
sandbox2 = FakeSandbox(SandboxConfig(), None)
sandbox2.start()
out2 = run_agent("demo-fail", "mbpp", "sys", "task", sandbox2, FakeLLM(),
                 Limits(max_iterations=3), lambda steps: "FALLBACK")

report("ECHEC - le modele n'appelle jamais final_answer",
       "success=False, error='max iterations reached', solution=FALLBACK",
       out2)
assert out2.success is False
assert out2.error == "max iterations reached"
assert out2.solution == "FALLBACK"
assert out2.iterations == 3
assert out2.steps[0].sandbox_output.strip() == "4"
print("  >>> ECHEC gere correctement : OK\n")


# --- success path (no network): step 1 prints, step 2 calls final_answer ---
SOURCE = "def add(a, b):\n    return a + b"
llm3 = ScriptedLLM([
    "Thought: I test first.\n```python\nprint(2 + 3)\n```",
    "Thought: now I submit.\n```python\n"
    f"final_answer('''{SOURCE}''')\n```",
])
sandbox3 = FakeSandbox(SandboxConfig(), None)
sandbox3.start()
out3 = run_agent("demo-ok", "mbpp", "sys", "task", sandbox3, llm3,
                 Limits(), lambda steps: "FALLBACK")

report("REUSSITE - tour 1 teste, tour 2 appelle final_answer",
       "success=True, error=None, solution=le code de add (pas FALLBACK)",
       out3)
assert out3.success is True
assert out3.error is None
assert out3.solution == SOURCE
assert out3.iterations == 2
assert out3.total_requests == 2
assert out3.total_input_tokens == 20 and out3.total_output_tokens == 20
assert out3.steps[0].sandbox_output.strip() == "5"
assert out3.steps[1].sandbox_input.startswith("final_answer(")
# the observation of step 1 must be sent back to the LLM at step 2
assert llm3.calls[1][-1] == {"role": "user", "content": "Observation:\n5"}
assert llm3.calls[1][-2]["role"] == "assistant"
print("  >>> REUSSITE geree correctement : OK\n")


# --- LLM crash path (no network): llm.chat raises an exception ---
class CrashingLLM:
    """Succeeds on the first call, then raises like a dead API."""

    def __init__(self, crash_at=1):
        self.crash_at = crash_at
        self.n = 0

    def chat(self, messages, max_tokens=1024, stop=None):
        self.n += 1
        if self.n >= self.crash_at:
            raise ConnectionError("API unreachable")
        return LLMResponse(text="Thought:\n```python\nprint(2+2)\n```",
                           input_tokens=10, output_tokens=10,
                           request_time_ms=0, retries=0,
                           api_url="fake", model_name="fake")


# crash on the very first call
sandbox4 = FakeSandbox(SandboxConfig(), None)
sandbox4.start()
out4 = run_agent("demo-crash", "mbpp", "sys", "task", sandbox4,
                 CrashingLLM(crash_at=1), Limits(), lambda steps: "FALLBACK")

report("CRASH LLM - l'appel API leve une exception des le tour 1",
       "pas d'exception, success=False, error='LLM call failed...', "
       "solution=FALLBACK",
       out4)
assert out4.success is False
assert out4.error.startswith("LLM call failed: ConnectionError")
assert "API unreachable" in out4.error
assert out4.solution == "FALLBACK"
assert out4.iterations == 0 and out4.steps == []
assert out4.total_requests == 0
print("  >>> CRASH au tour 1 gere correctement : OK\n")

# crash after one good step: the first step must be kept
sandbox5 = FakeSandbox(SandboxConfig(), None)
sandbox5.start()
out5 = run_agent("demo-crash2", "mbpp", "sys", "task", sandbox5,
                 CrashingLLM(crash_at=2), Limits(), lambda steps: "FALLBACK")

report("CRASH LLM - le tour 1 reussit, l'appel du tour 2 leve une exception",
       "success=False, 1 tour conserve, error='LLM call failed...'",
       out5)
assert out5.success is False
assert out5.error.startswith("LLM call failed")
assert out5.solution == "FALLBACK"
assert out5.iterations == 1
assert out5.steps[0].sandbox_output.strip() == "4"
print("  >>> CRASH au tour 2 gere correctement : OK\n")


# --- nominal path with the real LLM (only if url and model are given) ---
print("TEST AVEC UN VRAI AGENT IA -> a rentrer en lign de commande\n")
if len(sys.argv) >= 3:
    url, model = sys.argv[1], sys.argv[2]
    sandbox = FakeSandbox(SandboxConfig(), None)
    sandbox.start()
    out = run_agent("demo", "mbpp", SYSTEM + sandbox.manual(), USER,
                    sandbox, LLMClient(url, model), Limits(), lambda steps: "")
    print("success:", out.success, "| iterations:", out.iterations,
          "| error:", out.error)
    print("solution:\n", out.solution)

print("  >>> REUSSITE geree correctement : OK\n")

# to test:
#   uv run python scripts/try_agent.py
#   uv run python scripts/try_agent.py \
#       https://generativelanguage.googleapis.com/v1beta/openai/ \
#       gemini-3.5-flash-lite
