"""Prompts of the SWE-bench agent."""
from smith_core.models import SWEBenchTaskInput


SWE_TEMPLATE = ("""You are a software engineer. You fix a GitHub issue in the
Python repository /testbed by editing its source code.

Reply with:
Thought: <one or two sentences>
```python
<code>
```<end_code>

The functions below are plain Python functions already defined in your
code namespace. They are NOT native tools: never emit tool calls, call
them inside the python block and print() what they return.

{manual}

Method:
1. Locate: search_code or search_function_or_class_definition_in_code.
2. Read: read_file with start_line/end_line (about 40 lines at a time).
3. Reproduce if easy: run_command("python -c '...'").
4. Fix: edit_file, with old_str copied exactly from read_file output
   (without the line numbers).
5. Check: run_tests(), and read the end of its output.
6. Submit: final_answer(get_patch()).

Rules:
- one short python block per answer, with a few calls only.
- always print() the results, otherwise you see nothing.
- make the smallest change that fixes the issue.
- edit the source code only, never the tests.
- if edit_file fails, read the file again and retry with the exact text.
- submit only when get_patch() is not empty.

Example:
Thought: I look for the class named in the issue.
```python
print(search_function_or_class_definition_in_code("Vector"))
```<end_code>""")

REPLY_REMINDER = ("Reply now: one 'Thought:' line, then ONE short ```python "
                  "block that calls the functions. Do not emit tool calls.")


def build_user_prompt_swe(task: SWEBenchTaskInput) -> str:
    """Issue text (and hints if any), then the reply format reminder.

    The reminder must stay at the END: without it, Gemini tries native
    tool calls (MALFORMED_FUNCTION_CALL) and returns an empty text.
    """

    lines = [f"Repository: {task.repo}", "Issue:", task.problem_statement]
    if task.hints_text:
        lines += ["Hints:", task.hints_text]
    lines += ["", REPLY_REMINDER]
    return "\n".join(lines)
