*This project has been created as part of the 42 curriculum by slidriss, thmaille.*

# Agent Smith

## Description

Agent Smith is a **code agent** framework. It solves coding tasks on its own:
the LLM writes Python code, the code runs in a secure **sandbox**, the
output goes back to the LLM, and the cycle repeats until the task is solved.

It runs on two benchmarks:

| Benchmark | Task | What the agent submits |
|---|---|---|
| **MBPP** | small algorithmic Python problems | the function source code |
| **SWE-bench Verified** | real bugs in real open-source repositories (in Docker) | a git patch |


**Note — Rootless Docker on 42 workstations.** On school accounts,
the host's UID (for example, 102605) is outside the subuid range
managed by rootless Docker. This issue has already been raised during previous thesis defenses. 
When `validate swebench` copies `patch.diff` into the container,
the script creates a tar archive that preserves the host’s UID. 
Docker then fails with
`failed to Lchown “patch.diff” ... invalid argument`, and the task is
marked as FAILED even if the patch is correct.

To work around the problem without modifying the moulinette script, we run the
validation in a user namespace using `unshare -r`. Our UID is treated
as 0 there: the archived files therefore belong to root, and Docker can
extract them. The problem stems solely from the
evaluation environment; the agent itself is not affected.

```bash
cd moulinette
unshare -r uv run moulinette_eval validate swebench task.json solution.json
```

Main features:

- the agent loop is our own **Thought → Code → Observation** loop (we use no agent library) ;
- tools are called **from Python code** (`result = read_file(...)`), not through JSON tool calling ;
- the sandbox restricts imports, builtins, files, network, processes, time and memory ;
- the tools are served by our own **MCP servers** (stdio or streamable HTTP) ;
- the client works with any OpenAI-compatible LLM provider, and supports several API keys with rotation ;
- every step is fully logged in `solution.json` (tokens, latency, retries, raw LLM output, sandbox input/output).

## Instructions

### Requirements

- Python 3.10 and [uv](https://docs.astral.sh/uv/)
- Docker, for SWE-bench only (the images are `linux/amd64`)

### Installation

```bash
uv sync
cp .env.example .env      # then put your API keys in .env
```

API keys are **only** read from environment variables or from `.env`:
`<PROVIDER>_API_KEY`, then `<PROVIDER>_API_KEY_2`, `_3`, … for rotation.
The provider name comes from the URL (`https://api.groq.com/openai/v1` → `GROQ`).

### Interactive sandbox

```bash
uv run sandbox                                                          # default config
uv run sandbox sandbox_template.json                                    # custom config
uv run sandbox --mcp-stdio "python mcp_tools_mbpp.py" sandbox_template.json
```
To start an MCP server over HTTP: `python mcp_tools_mbpp.py --http [--port 8000]`.
Type `exit` or press Ctrl+D to quit the REPL.

```bash
uv run python mcp_tools_mbpp.py --http --port 8000
uv run sandbox --mcp-server http://127.0.0.1:8000/mcp                   # HTTP server
```
And, to test SWEBench with a define file (for example: copy of Agent-Smith's project):

```bash
rsync -a --exclude .venv --exclude __pycache__ . /tmp/smith-copy        # Create a copy of Agent-Smith without .venv
TESTBED_PATH=/tmp/smith-copy uv run sandbox --mcp-stdio "uv run python mcp_tools_swebench.py" sandbox_template.json
```


### MBPP agent

```bash
uv run python -m agent_mbpp --task-file ../cache/mbpp_task.json \
    --output ../cache/mbpp_solution.json \
    --model-name "model/name" --provider-url "https://provider.api/v1" \
    [--max-iterations 10]
```

### SWE-bench agent

```bash
uv run python -m agent_swebench --task-file ../cache/swebench_task.json \
    --output ../cache/swebench_solution.json \
    --model-name "model/name" --provider-url "https://provider.api/v1"
```

### Tests

```bash
uv run pytest tests/ -v
```

## System architecture

```
                      ┌───────────────────────────── host ─────────────────────────────┐
 task.json ──► agent_mbpp / agent_swebench (CLI)
                      │
                      ▼
              ┌───────────────┐   messages    ┌──────────────┐
              │  Agent loop   │ ────────────► │  LLMClient   │ ──► OpenAI-compatible API
              │  (loop.py)    │ ◄──────────── │ + KeyRing    │     (Groq, OpenRouter, Gemini…)
              └───────┬───────┘   raw text    └──────────────┘
                      │ extract_code()  (python / XML invoke / Hermes / ReAct → Python)
                      ▼
              ┌───────────────────────────────────────────┐
              │ Sandbox (parent process)                  │
              │   ├─ McpClient ──stdio / HTTP──► MCP server (mcp_tools_*.py)
              │   │                                 │  SWE-bench: docker exec ──► container /testbed
              │   └─ Pipe ◄──► child process (spawn)│
              │          exec() with safe builtins, import guard,
              │          AST check, audit hook, RLIMIT_AS
              └───────────────────────────────────────────┘
                      │ ExecResult (output, final_answer, notices, timed_out)
                      ▼
               Observation ──► next LLM turn … ──► solution.json
```

```
smith_core/
├── models.py            Pydantic models: SandboxConfig, task inputs, StepMetrics, SolutionOutput, ExecResult
├── llm/
│   ├── clients.py       LLMClient: OpenAI-compatible chat call, retries, usage tracking
│   └── keys.py          KeyRing: several keys per provider + rotation
├── agent/
│   ├── loop.py          run_agent(): the Thought → Code → Observation loop and the budgets
│   ├── extract.py       extract_code(): tries every format, builds the notices
│   ├── formats.py       one parser per output format
│   ├── helpers.py       converts a tool call into a Python line
│   └── prompts.py       inserts the sandbox manual into a prompt template
└── sandbox/
    ├── executor.py      Sandbox: child process, timeout, crash, truncation, MCP dispatch
    ├── security.py      import guard, safe builtins, AST check, safe open, audit hook
    ├── mcp_client.py    McpClient: stdio + streamable HTTP, tools / resources / prompts
    ├── manual.py        builds the tool manual from the MCP schemas
    └── cli.py           `uv run sandbox` REPL
agent_mbpp/              MBPP CLI, prompt, fallback solution
agent_swebench/          SWE-bench CLI, Docker lifecycle (docker.py)
mcp_tools_mbpp.py        MCP server: run_tests
mcp_tools_swebench.py    MCP server: the 9 mandatory SWE-bench tools
sandbox_template.json    sandbox configuration
tests/                   pytest suites (sandbox security, MCP client, tools, extraction…)
```

The layers are independent. The tools work without the agent, the sandbox
works without the LLM (REPL), and the loop only needs an object with an
`execute(code)` method.

## Agent loop

`run_agent()` in `smith_core/agent/loop.py`:

```
messages = [system prompt (template + sandbox manual), user prompt (task)]
for step in 1..max_iterations:
    if not budget_left(): stop                   # time, input and output tokens
    text  = llm.chat(messages, stop=["<end_code>"])
    code, notice = extract_code(text)
    if code is None:   observation = notice      # "No valid code block found…"
    else:              result = sandbox.execute(code)
                       observation = notices + output
    record StepMetrics(tokens, latency, retries, llm_output, sandbox_input, sandbox_output)
    if final_answer was called: stop
    messages += [assistant: text, user: "Observation:\n" + observation]
solution = final answer, or fallback(steps) if the agent never called final_answer
```

- **Thought → Code → Observation**: the prompt asks for `Thought:`, then a
  ```` ```python ```` block ending with `<end_code>`.
- **Stop sequence**: `<end_code>` stops the generation, so the model cannot
  invent a fake `Observation:`. If it still writes one, everything after it
  is ignored and the model gets a note about it.
- **Several output formats**: `extract_code` tries Python blocks first, then
  Anthropic-style `<invoke>` XML, Hermes `<tool_call>` JSON and ReAct
  `Action:` / `Action Input:`. Non-Python formats are turned into a Python
  call (`result = read_file(filepath='...')` + `print(result)`), so the
  sandbox only ever receives Python.
- **Explicit feedback**: the LLM is told when there is no code block, when
  a block was not closed but ran anyway, when several blocks were joined,
  when non-Python blocks were skipped, when the code timed out, and when the
  output was truncated.
- **Budgets**: before each call, `budget_left()` checks the elapsed time (plus the
  slowest request so far) and the remaining output tokens. It also estimates the next
  input size (previous input + previous output + a margin). `max_tokens` of each
  call is capped by what is left. MBPP limits are 10 iterations,
  6 000 input tokens, 1 500 output tokens and 120 s. SWE-bench limits are 30, 300 000, 10 000 and 900 s.
- **Usage tracking**: every step stores its input/output tokens, the request time,
  the API URL, the model name and the number of retries. The totals go in `SolutionOutput`.
- **Robustness**: the CLI always writes a valid `solution.json`, even
  when the task file, the LLM or the sandbox fails (`error` field).

LLM client (`smith_core/llm/clients.py`): one OpenAI-compatible client, so changing
provider only means changing `--provider-url`. On a 429, a 5xx error or a
connection error, it rotates to the next key of the `KeyRing` and retries
with exponential backoff (up to 3 retries, counted in `StepMetrics.retries`).

## Sandbox design

The sandbox (`smith_core/sandbox/`) is the safety boundary between the
LLM-generated code and the machine. It uses **only the standard library**.

### Isolation: a child process

The code runs in a **separate child process**, started with
`multiprocessing` in `spawn` mode. Parent and child talk through a `Pipe`.

| Why a child process | |
|---|---|
| Timeout | a stuck `while True` cannot be stopped from inside the same process. A child can be **killed** |
| Crash | a segfault or an out-of-memory error kills the child, not the agent |
| Memory | `RLIMIT_AS` applies to the child only |
| Persistent state | the child keeps one namespace, so variables survive between steps |

The child messages are: `stdout` (streamed live by `_PipeStdout`), `tool` (MCP
call request) and `done` (end of execution, with `final`, `error` and
optionally `control`).

### Security layers

| Threat | Protection | Where |
|---|---|---|
| `import os` / `subprocess` / `socket` | **import allowlist**: `__import__` is replaced in the sandbox builtins. `pkg.*` allows submodules, relative imports are refused, `from pkg import submodule` is checked too | `make_guarded_import` |
| `eval`, `exec`, `compile`, `input`, `breakpoint`, `globals`, `vars`… | removed from a **copy** of the builtins (the real ones are not touched) | `build_safe_builtins` |
| Escapes via `().__class__.__subclasses__()`, `f.__globals__`… | **AST check** before `exec`: every dunder attribute and name is refused (except `__name__`, `__import__`). `getattr(x, "__class__")` is blocked by `safe_getattr` | `check_ast`, `safe_getattr` |
| Reading/writing files outside the workspace | `open` only accepts paths inside `allowed_directories` (both sides resolved with `realpath`, so `..` and symlinks cannot escape) | `make_safe_open` |
| Indirect access (an allowed module that uses `os` inside, e.g. `random._os.system`) | **audit hook** (`sys.addaudithook`, PEP 578), installed in the child: it blocks every `open` outside the allowed dirs (read-only is allowed in the Python install), and every `socket.*`, `subprocess.*`, `os.system`, `os.exec*`, `os.spawn*`, `os.fork`, `os.kill`, `ctypes.*` event | `make_audit_hook` |
| Network | the import guard (no `socket`/`urllib`), plus the audit hook on `socket.*` events | |
| Infinite loop | the parent waits with `conn.poll(remaining)`. After `max_execution_time_seconds` it kills the child and starts a fresh one. The partial output is returned with a notice. The timer is **paused during MCP tool calls** (tools run outside the sandbox) | `Sandbox.execute`, `_on_timeout` |
| Memory bomb | `resource.setrlimit(RLIMIT_AS, max_memory_mb)` in the child. A `MemoryError` is reported clearly. If the child dies, it is restarted (`_on_crash`). Note: `RLIMIT_AS` is ignored by macOS but enforced on Linux | `_limit_memory` |
| Huge outputs | the output keeps its head and tail (10 000 characters max), and the LLM gets a notice with the number of omitted characters | `_truncate` |

`final_answer(x)` raises a private `FinalAnswer` exception. It inherits from
`BaseException`, so a `try/except Exception` in the LLM code cannot catch
it. The child sends the value to the parent, and the loop stops.

`SystemExit` and `KeyboardInterrupt` are **not swallowed**. The child sends them
as a `control` message, and the parent raises them again, so they reach the
agent loop.

### Configuration

The limits come from a Pydantic `SandboxConfig`, loaded from JSON
(`sandbox_template.json`):

```json
{
  "authorized_imports": ["math", "math.*", "collections", "collections.*", "itertools", "re", "..."],
  "allowed_directories": ["/testbed", "/tmp/agent"],
  "max_execution_time_seconds": 30,
  "max_memory_mb": 512
}
```

### MCP integration

- `McpClient` runs the async MCP session in a background thread. The
  sandbox calls it synchronously.
- **Transports**: `McpClient.from_stdio(command)` starts the server as a
  sub-process. `McpClient.from_http(url)` uses streamable HTTP. Both share the
  same code; only the transport factory changes.
- **Dynamic discovery**: when the sandbox starts, it lists the server's tools,
  resources and prompts. For each tool it builds a Python wrapper in the
  child namespace. The wrapper sends `{"type": "tool", ...}` through the pipe,
  the parent calls the MCP tool, and the result comes back as the return value.
  Positional arguments are mapped to the schema parameter names.
  If the server has resources or prompts, `read_resource(uri)` and
  `get_prompt(name, arguments)` are also added.
- `final_answer` is **not** an MCP tool. It is always there, whatever the server.
- **Manual**: `Sandbox.manual()` builds the tool documentation from the
  server's JSON schemas: signature with Python types and defaults, first line
  of the description, the `Returns:` line, then the resources, the prompts,
  the allowed imports, the directories and the limits. Connecting another
  server changes the manual automatically. This manual is inserted into
  the system prompt (`{manual}`).

## Tool implementation

### MBPP server (`mcp_tools_mbpp.py`)

- `run_tests(code, test_list)` runs the solution and the asserts in a **new
  isolated Python process** (`python -I`, temporary working directory,
  10 s timeout). It returns `{"success": bool, "output": str}` as JSON, with one
  `PASS:` / `FAIL:` line per assert.
- The server also exposes a resource (`mbpp://guide`) and a prompt (`solve_task`).

### SWE-bench server (`mcp_tools_swebench.py`)

The repository root comes from the **`TESTBED_PATH`** environment variable (default
`/testbed`). The server has two modes, chosen with one variable:

| Mode | When | How a command runs |
|---|---|---|
| local | moulinette tool tests, our pytest | `bash -c <cmd>` with `cwd` |
| Docker | `SWEBENCH_CONTAINER=<name>` is set | `docker exec -i -w <cwd> <name> bash -c <cmd>` |

So we use option (b) of the subject: the sandbox runs on the host, and the
MCP tools bridge into the container. All tools go through three helpers:

- `_sh(command, workdir, timeout, stdin)`: runs a command and returns `(code, stdout, stderr)`. It never raises: timeout → code 124, command not found → code 1 with a message ;
- `_read` / `_write`: read and write files with Python locally, or with `cat` / `cat >` (through stdin) in Docker ;
- `_abs(path)`: relative paths are resolved from the repository root and normalised.

Every value coming from the LLM is quoted with `shlex.quote`. Long outputs are
cut at 10 000 characters, with a clear message.

| Tool | Implementation | Output |
|---|---|---|
| `read_file(filepath, start_line=1, end_line=None)` | reads the file, validates the range | `n: line` (like `cat -n`), errors for an empty file, an out-of-range line or `end < start` |
| `edit_file(filepath, old_str, new_str)` | `old_str` must appear **exactly once**. For `.py` files, the new content is checked with `compile()` **before** writing: on a syntax error the file is not modified and the LLM is told | `Edited <file> at line N.` |
| `list_files(directory=".", pattern="*")` | `find -type f -name <pattern>`, `.git` excluded, sorted | absolute paths, or `No files found.` |
| `search_code(pattern, file_pattern="*.py")` | `grep -rnIE` (extended regex, binary files skipped, `.git` excluded). Exit code 1 means no match, not an error | `/abs/path.py:<line> <content>` |
| `search_function_or_class_definition_in_code(name)` | checks that `name` is a valid identifier, then searches `^\s*(async\s+)?(def\|class)\s+NAME\b` | same format as `search_code` |
| `find_references(name, filepath, line)` | checks that `name` really is at `filepath:line`, then `grep -rnIwF` (whole word, literal text) | same format as `search_code` |
| `run_command(command, workdir=".")` | `bash -c` in the workdir, 120 s timeout | `exit_code`, `stdout`, `stderr` |
| `run_tests()` | runs the evaluation script (`EVAL_SCRIPT_PATH`, default `/eval.sh`), 600 s timeout. The **end** of the output is kept, because the test summary is there | `exit_code`, `stdout`, `stderr` |
| `get_patch()` | `git -c core.fileMode=false diff` in the repository (never truncated) | unified diff |

The tools are tested on their own in `tests/test_tools_swebench.py`. The fixture
builds a small git repository in a temporary folder and points `TESTBED_PATH`
at it, exactly like the moulinette does.

## Benchmark results and analysis

The full report is in [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md). The backing
`solution.json` files are in `benchmark/`.

> TODO: summary table (5 models × 3 SWE-bench tasks), the selected model and why.

## Resources

- [Model Context Protocol – specification](https://modelcontextprotocol.io/) and the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [smolagents – CodeAgent](https://huggingface.co/docs/smolagents/conceptual_guides/intro_agents) (idea of code-based tool calling; not used as a library)
- *Executable Code Actions Elicit Better LLM Agents* (CodeAct), Wang et al., 2024
- *ReAct: Synergizing Reasoning and Acting in Language Models*, Yao et al., 2022
- [SWE-bench](https://www.swebench.com/) and *SWE-agent: Agent-Computer Interfaces*, Yang et al., 2024
- *Program Synthesis with Large Language Models* (MBPP), Austin et al., 2021
- Python docs: [`multiprocessing`](https://docs.python.org/3/library/multiprocessing.html), [`sys.addaudithook` / PEP 578](https://peps.python.org/pep-0578/), [`ast`](https://docs.python.org/3/library/ast.html), [`resource`](https://docs.python.org/3/library/resource.html)
- [OpenAI Python client](https://github.com/openai/openai-python) (used with OpenAI-compatible providers)

### How AI was used

- **Explanations and design discussions**: we used Claude to explain concepts
  (audit hooks, `spawn`, MCP transports, the SWE-bench Docker images) and to discuss the
  trade-offs between options. We made the design choices together, as a team.
- **Guided coding**: for the sandbox and the tools, the AI mostly gave hints and
  code with blanks to fill. We wrote and corrected the code ourselves, then
  reviewed it line by line.
- **Tests**: AI helped draft some pytest cases (for example the git fixture of
  `tests/test_tools_swebench.py`). We reviewed them and adapted them.
- **Documentation**: this README was drafted with AI from our code, then
  reviewed and corrected by us.
- The agent code itself solves the tasks with the LLM providers listed in the
  benchmark report. No solution comes from pull requests, issues or other external sources.
