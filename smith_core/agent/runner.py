import argparse
from argparse import Namespace
from pathlib import Path

from smith_core.models import SolutionOutput


def parse_args(benchmark_name: str, default_iterations: int) -> Namespace:
    """Parse the command-line arguments of an agent."""

    parser = argparse.ArgumentParser(
        description=f"Run the {benchmark_name} agent on one task"
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
        default=default_iterations,
        help="Maximum number of agent iterations "
             f"(default: {default_iterations})."
    )
    return parser.parse_args()


def write_solution(solution: SolutionOutput, output_path: Path) -> None:
    """Write the solution as JSON, creating parent folders if needed."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(solution.model_dump_json(indent=2))


def failed_solution(task_id, benchmark: str, error,
                    solution: str = "",
                    total_time_seconds: float = 0.0) -> SolutionOutput:
    """Build a valid failed SolutionOutput (all counters at zero).

    solution can carry a partial answer (e.g. the current git diff),
    benchmark is "mbpp" or "swebench".
    """

    return SolutionOutput(
        task_id=str(task_id),
        benchmark=benchmark,
        success=False,
        solution=solution,
        iterations=0,
        total_requests=0,
        total_input_tokens=0,
        total_output_tokens=0,
        total_time_seconds=total_time_seconds,
        error=f"{type(error).__name__}: {error}"
    )
