import inspect
import json
import sys
import mcp_tools_mbpp
from agent_mbpp.prompts_mbpp import (MBPP_TEMPLATE, build_user_prompt_mbpp)
from smith_core.agent.prompts import build_system_prompt
from smith_core.agent.loop import (OBSERVATION_MARGIN, Limits,
                                   run_agent)
from smith_core.llm.clients import LLMClient
from smith_core.models import MBPPTaskInput, SandboxConfig
from smith_core.sandbox.fake import FakeSandbox


DATA = "moulinette/moulinette/mbpp/data/sanitized_tasks.json"
FIELDS = ("task_id", "task_definition", "function_definition",
          "test_imports", "test_list")
MAX_SYSTEM_TOKENS = 700
CHARS_PER_TOKEN = 3  # pessimistic: code and JSON tokenize worse than prose
ASSUMED_OUTPUT_TOKENS = 300  # one Thought + one code block
# Worst-case manual: final_answer + the FULL run_tests docstring.
REALISTIC_MANUAL = (
    "- final_answer(answer: str): submit your solution and stop.\n"
    "- run_tests(code: str, test_list: list[str]) -> str:\n"
    + inspect.cleandoc(mcp_tools_mbpp.run_tests.__doc__)
)


def load_task(with_imports):
    """Return the first real MBPP task with (or without) test imports."""
    with open(DATA) as f:
        tasks = json.load(f)
    raw = next(t for t in tasks if bool(t["test_imports"]) == with_imports)
    return MBPPTaskInput(**{k: raw[k] for k in FIELDS})


def estimate_tokens(text):
    """Offline, pessimistic token estimate (no tokenizer installed)."""
    return -(-len(text) // CHARS_PER_TOKEN)


def load_all_tasks():
    """Return every MBPP task as a MBPPTaskInput."""
    with open(DATA) as f:
        return [MBPPTaskInput(**{k: t[k] for k in FIELDS})
                for t in json.load(f)]


class RealManualSandbox(FakeSandbox):
    """FakeSandbox whose manual is as long as the real one will be."""

    def manual(self):
        return REALISTIC_MANUAL


def check(title, condition):
    """Print and assert one check."""
    print(f"  {'OK ' if condition else 'KO '} {title}")
    assert condition, title


# --- 1. system prompt -------------------------------------------------
print("=" * 64)
print("SYSTEM PROMPT")
print("=" * 64)
manual = "- final_answer(answer: str): submit your solution."
system = build_system_prompt(MBPP_TEMPLATE, manual)
check("{manual} is gone", "{manual}" not in system)
check("manual is inserted", manual in system)
check("template is not modified", "{manual}" in MBPP_TEMPLATE)
check("example is intact", 'json.loads(r)["success"]' in system)
check("example uses TESTS", "test_list=TESTS" in system)
check("<end_code> format is present", "<end_code>" in system)
check("inspect rule is present", "inspect" in system)
print(f"  size: {len(system)} characters, {len(system.split())} words\n")

# --- 2. user prompt ---------------------------------------------------
print("=" * 64)
print("USER PROMPT")
print("=" * 64)
for with_imports in (False, True):
    task = load_task(with_imports)
    user = build_user_prompt_mbpp(task)
    print(f"--- task {task.task_id} (test_imports: {with_imports}) ---")
    print(user)
    print()
    check("contains the task definition", task.task_definition in user)
    check("contains the signature", task.function_definition in user)
    check("contains all the tests",
          all(t in user for t in task.test_list))
    check("imports section present only if there are imports",
          ("Test imports:" in user) == with_imports)
    check("mentions variable TESTS", "variable TESTS" in user)
    check("returns a str", isinstance(user, str))
    print()

# --- 3. offline stress tests -------------------------------------------
print("=" * 64)
print("OFFLINE STRESS TESTS (pessimistic estimate, 1 token = 3 chars)")
print("=" * 64)
realistic_system = build_system_prompt(MBPP_TEMPLATE, REALISTIC_MANUAL)
sys_tokens = estimate_tokens(realistic_system)
print(f"  system prompt + realistic manual: ~{sys_tokens} tokens")
check(f"system prompt + realistic manual <= {MAX_SYSTEM_TOKENS}",
      sys_tokens <= MAX_SYSTEM_TOKENS)

tasks = load_all_tasks()
users = {t.task_id: build_user_prompt_mbpp(t) for t in tasks}
sizes = sorted(estimate_tokens(u) for u in users.values())
p99 = sizes[int(len(sizes) * 0.99)]
longest_id = max(users, key=lambda k: len(users[k]))
print(f"  user prompt size over {len(sizes)} tasks: median "
      f"~{sizes[len(sizes) // 2]}, p99 ~{p99}, max ~{sizes[-1]} "
      f"(task {longest_id})")


def turns_that_fit(user_tokens, per_turn_growth):
    """Count turns before the cumulative input budget is exhausted."""
    total, turn_input, turns = 0, sys_tokens + user_tokens, 0
    while total + turn_input <= Limits().max_input_tokens:
        total += turn_input
        turns += 1
        turn_input += per_turn_growth
    return turns


# budget_left reserves OBSERVATION_MARGIN per turn: the strict rule.
strict = ASSUMED_OUTPUT_TOKENS + OBSERVATION_MARGIN
# A typical observation (print of a run_tests result) is much smaller.
typical = ASSUMED_OUTPUT_TOKENS + 150
for label, tokens in (("typical task (p99)", p99),
                      (f"longest task ({longest_id})", sizes[-1])):
    print(f"  {label}: {turns_that_fit(tokens, typical)} turns "
          f"(typical observation), {turns_that_fit(tokens, strict)} "
          f"turns (budget_left margin {OBSERVATION_MARGIN})")
check("p99 task: >= 3 turns even with the budget_left margin",
      turns_that_fit(p99, strict) >= 3)
check("longest task: >= 3 turns with typical observations",
      turns_that_fit(sizes[-1], typical) >= 3)
check("longest task: >= 2 turns even with the budget_left margin",
      turns_that_fit(sizes[-1], strict) >= 2)

over = [i for i, u in users.items()
        if estimate_tokens(u) + sys_tokens > 1500]
check(f"no task exceeds 1500 tokens on turn 1 (over: {over[:5]})",
      not over)
print()

# --- 4. real LLM measurements (url and model on the command line) ------
print("=" * 64)
print("REAL TOKEN MEASUREMENTS")
print("=" * 64)
if len(sys.argv) >= 3:
    url, model = sys.argv[1], sys.argv[2]
    llm = LLMClient(url, model)

    def first_turn_tokens(user_prompt, manual_sandbox):
        """Run ONE turn and return the real input_tokens."""
        manual_sandbox.start()
        sys_prompt = build_system_prompt(MBPP_TEMPLATE,
                                         manual_sandbox.manual())
        out = run_agent("demo", "mbpp", sys_prompt, user_prompt,
                        manual_sandbox, llm, Limits(max_iterations=1),
                        lambda steps: "")
        return out.steps[0].input_tokens

    cfg = SandboxConfig()
    base = first_turn_tokens("hi", FakeSandbox(cfg, None))
    real = first_turn_tokens("hi", RealManualSandbox(cfg, None))
    full = first_turn_tokens(users[longest_id],
                             RealManualSandbox(cfg, None))
    print(f"  FakeSandbox manual + 'hi'        : {base} tokens")
    print(f"  realistic manual + 'hi'          : {real} tokens")
    print(f"  realistic manual + longest task  : {full} tokens")
    check(f"system prompt + realistic manual <= {MAX_SYSTEM_TOKENS}",
          real <= MAX_SYSTEM_TOKENS)
    check("estimate is pessimistic (estimate >= real)",
          sys_tokens >= real - 20)
else:
    print("  skipped: pass a url and a model to measure")

# to test:
#   uv run python scripts/try_prompts.py
#   uv run python scripts/try_prompts.py \
#       https://generativelanguage.googleapis.com/v1beta/openai/ \
#       gemini-3.5-flash-lite
