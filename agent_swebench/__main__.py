import shlex
import sys
from pathlib import Path

from agent_mbpp.fallback import last_def_solution
from agent_mbpp.prompts_mbpp import MBPP_TEMPLATE, build_user_prompt_mbpp
from smith_core.agent.loop import Limits, run_agent
from smith_core.agent.runner import (parse_args, write_solution,
                                     failed_solution)
from smith_core.agent.prompts import build_system_prompt
from smith_core.llm.clients import LLMClient
from smith_core.models import MBPPTaskInput, SandboxConfig
from smith_core.sandbox.executor import Sandbox
from smith_core.sandbox.mcp_client import McpClient


ROOT = Path(__file__).resolve().parent.parent

# Used while Sandbox.manual() is not written yet (it returns None).
FALLBACK_MANUAL = (
    "- final_answer(answer: str): submit your solution and stop.\n"
    "- run_tests(code: str, test_list: list[str]) -> str: run the asserts "
    "against your code. Returns JSON {\"success\": bool, \"output\": str}."
)


def load_task(path: Path) -> MBPPTaskInput:
    """Read the task JSON file and return it as a MBPPTaskInput."""

    return MBPPTaskInput.model_validate_json(path.read_text())


def main() -> None:
    """Solve one MBPP task and always write a solution JSON file."""

    args = parse_args("mbpp", 10)
    try:
        task = load_task(args.task_file)
        server = shlex.join([sys.executable, str(ROOT / "mcp_tools_mbpp.py")])
        sandbox = Sandbox(SandboxConfig(), McpClient.from_stdio(server))
    except Exception as error:
        write_solution(failed_solution("unknown", "mbpp", error),
                       args.output)
        return
    try:
        sandbox.start()
        sandbox.execute(f"TESTS = {task.test_list!r}")
        manual = sandbox.manual() or FALLBACK_MANUAL
        solution = run_agent(
            str(task.task_id), "mbpp",
            build_system_prompt(MBPP_TEMPLATE, manual),
            build_user_prompt_mbpp(task),
            sandbox,
            LLMClient(args.provider_url, args.model_name),
            Limits(max_iterations=args.max_iterations),
            lambda steps: last_def_solution(steps,
                                            task.function_definition),
        )
    except Exception as error:
        solution = failed_solution(task.task_id, "mbpp", error)
    finally:
        try:
            sandbox.close()
        except Exception:
            pass
    write_solution(solution, args.output)


if __name__ == "__main__":
    main()
