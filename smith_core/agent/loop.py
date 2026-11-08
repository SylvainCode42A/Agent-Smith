import time
from dataclasses import dataclass
from smith_core.models import StepMetrics
from smith_core.agent.extract import extract_code

@dataclass
class Limits:
    max_iterations: int = 10
    max_input_tokens: int = 100000
    max_output_tokens: int = 20000
    timeout_s: int = 20


def run_agent(task_id, benchmark, system_prompt, user_prompt, sandbox, llm, limits, fallback):
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}]
    steps: list[StepMetrics] = []
    start = time.monotonic()
    answer = None
    for i in range(1, limits.max_iterations + 1):
        if not budget_left(steps, limits, start):
            break
        remaining_output_tokens = limits.max_output_tokens - sum(
            step.output_tokens for step in steps
        )
        resp = llm.chat(messages, max_tokens=remaining_output_tokens, stop=["<end_code>"])
        code, notice = extract_code(resp.text)
        if code is None:
            observation = notice                         # "No valid code block found..."
        else:
            result = sandbox.execute(code)
            observation = format_observation(result, notice)
            answer = result.final_answer
        steps.append(StepMetrics(step=i, input_tokens=resp.input_tokens, ...))  # TODO: tous les champs
        if answer is not None:
            break
        messages.append({"role": "assistant", "content": resp.text})
        messages.append({"role": "user", "content": "Observation:\n" + observation})
    ...  # TODO: construire SolutionOutput (success = answer is not None, solution = answer or fallback())
