import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from agent_swebench.docker import (launch_docker, start_container,
                                   copy_eval_script, remove_container)
from agent_swebench.prompt_swe import SWE_TEMPLATE, build_user_prompt_swe
from smith_core.agent.loop import Limits, run_agent
from smith_core.agent.runner import (parse_args, write_solution,
                                     failed_solution)
from smith_core.agent.prompts import build_system_prompt
from smith_core.llm.clients import LLMClient
from smith_core.models import SWEBenchTaskInput, SandboxConfig
from smith_core.sandbox.executor import Sandbox
from smith_core.sandbox.mcp_client import McpClient


ROOT = Path(__file__).resolve().parent.parent
BENCHMARK = "swebench"
EVAL_SCRIPT_PATH = "/tmp/agent/eval.sh"   # where copy_eval_script writes

TIME_LIMIT_S = 900        # the moulinette sends SIGTERM after that
CLEANUP_MARGIN_S = 60     # kept for git diff, JSON, close, docker rm
PATCH_TIMEOUT = 5         # git diff: short, may run during SIGTERM

MAX_INPUT_TOKENS = 300_000
MAX_OUTPUT_TOKENS = 10_000


def current_patch(name: str) -> str:
    """Return the current git diff of /testbed in the container.

    Never raises: returns "" if docker fails or times out.
    """
    try:
        res = launch_docker(["exec", name, "git", "-C", "/testbed",
                             "-c", "core.fileMode=false", "diff"],
                            timeout=PATCH_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    if res.returncode != 0:
        return ""
    return res.stdout


def on_sigterm(signum, frame) -> None:
    """Turn SIGTERM into SystemExit so that the finally blocks run."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    sys.exit(128 + signum)


def load_task(path: Path) -> SWEBenchTaskInput:
    """Read the task JSON file and return it as a SWEBenchTaskInput."""

    return SWEBenchTaskInput.model_validate_json(path.read_text())


def container_name(instance_id: str) -> str:
    """Unique Docker name: instance_id + pid, only [a-zA-Z0-9_.-]."""

    safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "-", instance_id)
    return f"smith-{safe_id}-{os.getpid()}"


def make_sandbox(name: str) -> Sandbox:
    """Sandbox connected to the SWE-bench MCP server of this container."""

    os.environ["SWEBENCH_CONTAINER"] = name
    os.environ["EVAL_SCRIPT_PATH"] = EVAL_SCRIPT_PATH
    server = shlex.join([sys.executable,
                         str(ROOT / "mcp_tools_swebench.py")])
    return Sandbox(SandboxConfig(), McpClient.from_stdio(server))


def make_limits(max_iterations: int, start: float) -> Limits:
    """SWE-bench limits, timeout computed from the time still left."""

    elapsed = time.monotonic() - start
    timeout_s = int(TIME_LIMIT_S - elapsed - CLEANUP_MARGIN_S)
    if timeout_s <= 0:
        raise RuntimeError(f"No time left for the agent "
                           f"({elapsed:.0f}s spent before starting)")
    return Limits(max_iterations=max_iterations,
                  max_input_tokens=MAX_INPUT_TOKENS,
                  max_output_tokens=MAX_OUTPUT_TOKENS,
                  timeout_s=timeout_s)


def main() -> None:
    """Solve one SWE-bench task, always write the JSON and remove
    the container."""

    start = time.monotonic()
    args = parse_args(BENCHMARK, 30)
    try:
        task = load_task(args.task_file)
    except Exception as error:
        # No container yet: nothing to clean.
        write_solution(failed_solution("unknown", BENCHMARK, error),
                       args.output)
        return

    name = container_name(task.instance_id)
    signal.signal(signal.SIGTERM, on_sigterm)
    solution = None
    sandbox = None
    try:
        start_container(task.docker_image, name)
        copy_eval_script(name, task.eval_script)
        sandbox = make_sandbox(name)
        sandbox.start()
        solution = run_agent(
            task.instance_id, BENCHMARK,
            build_system_prompt(SWE_TEMPLATE, sandbox.manual()),
            build_user_prompt_swe(task),
            sandbox,
            LLMClient(args.provider_url, args.model_name),
            make_limits(args.max_iterations, start),
            lambda _steps: current_patch(name),
        )
    except Exception as error:
        solution = failed_solution(task.instance_id, BENCHMARK, error,
                                   solution=current_patch(name),
                                   total_time_seconds=time.monotonic()
                                   - start)
    finally:
        try:
            if solution is None:   # SystemExit (SIGTERM) or Ctrl-C
                solution = failed_solution(
                    task.instance_id, BENCHMARK,
                    RuntimeError("interrupted (SIGTERM)"),
                    solution=current_patch(name),
                    total_time_seconds=time.monotonic() - start)
            write_solution(solution, args.output)
        except Exception:
            pass
        try:
            if sandbox is not None:
                sandbox.close()
        except Exception:
            pass
        remove_container(name)


if __name__ == "__main__":
    main()
