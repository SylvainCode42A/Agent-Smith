import argparse
import shlex
import sys
from argparse import Namespace
from pathlib import Path

from agent_mbpp.prompts_mbpp import MBPP_TEMPLATE, build_user_prompt_mbpp
from smith_core.agent.loop import Limits, run_agent
from smith_core.agent.prompts import build_system_prompt
from smith_core.llm.clients import LLMClient
from smith_core.models import MBPPTaskInput, SandboxConfig, SolutionOutput
from smith_core.sandbox.executor import Sandbox
from smith_core.sandbox.mcp_client import McpClient


ROOT = Path(__file__).resolve().parent.parent

# Used while Sandbox.manual() is not written yet (it returns None).
FALLBACK_MANUAL = (
    "- final_answer(answer: str): submit your solution and stop.\n"
    "- run_tests(code: str, test_list: list[str]) -> str: run the asserts "
    "against your code. Returns JSON {\"success\": bool, \"output\": str}."
)


def parse_args() -> Namespace:
    """Function to describe the allowed flag in the CLI"""

    parser = argparse.ArgumentParser(
        description="Run the MBPP agent on one task"
    )
    parser.add_argument(
        "--task-file",
        type=Path,
        required=True,
        help="Path to task JSON file."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path of the solution JSON file to write."
    )
    parser.add_argument(
        "--model-name",
        type=str,
        required=True,
        help="Name of the LLM model to use."
    )
    parser.add_argument(
        "--provider-url",
        type=str,
        required=True,
        help="Base URL of the LLM provider API."
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum number of agent iterations (default: 10)."
    )
    return parser.parse_args()


def load_task(path: Path) -> MBPPTaskInput:
    """Read the task JSON file and return it as a MBPPTaskInput."""

    return MBPPTaskInput.model_validate_json(path.read_text())


def write_solution(solution: SolutionOutput, output_path: Path) -> None:
    """Write the solution as JSON, creating parent folders if needed."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(solution.model_dump_json(indent=2))


def failed_solution(task_id, error) -> SolutionOutput:
    """Build a valid failed SolutionOutput (all counters at zero)."""

    return SolutionOutput(
        task_id=str(task_id),
        benchmark="mbpp",
        success=False,
        solution="",
        iterations=0,
        total_requests=0,
        total_input_tokens=0,
        total_output_tokens=0,
        total_time_seconds=0.0,
        error=f"{type(error).__name__}: {error}"
    )


def main() -> None:
    """Solve one MBPP task and always write a solution JSON file."""

    args = parse_args()
    try:
        task = load_task(args.task_file)
    except Exception as error:
        write_solution(failed_solution("unknown", error), args.output)
        return

    server = shlex.join([sys.executable, str(ROOT / "mcp_tools_mbpp.py")])
    sandbox = Sandbox(SandboxConfig(), McpClient.from_stdio(server))
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
            lambda: "",
        )
    except Exception as error:
        solution = failed_solution(task.task_id, error)
    finally:
        try:
            sandbox.close()
        except Exception:
            pass
    write_solution(solution, args.output)


if __name__ == "__main__":
    main()
