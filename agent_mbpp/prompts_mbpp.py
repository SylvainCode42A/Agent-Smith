from smith_core.models import MBPPTaskInput


MBPP_TEMPLATE = ("""You solve a Python task. Reply with:
Thought: <one or two sentences>
```python
<code>
```<end_code>

Tools available in the code:
{manual}

Rules:
- define the function with the exact given signature.
- the task's tests are in the variable TESTS: pass it as test_list.
- put the test imports inside the solution string.
- call final_answer only if the tests passed.
- pass the source code string to final_answer, not the function object.
- do not use "inspect".
- if the tests fail, read the output and correct it on the next step.
- give one python block per answer.

Example:
Thought: I write the function and test it before submitting.
```python
import json
solution = '''def add(a, b):
    return a + b'''
r = run_tests(code=solution, test_list=TESTS)
print(r)
if json.loads(r)["success"]:
    final_answer(solution)
```<end_code>""")


def build_user_prompt_mbpp(task: MBPPTaskInput) -> str:
    lines = []

    lines.append("Task: " + task.task_definition)
    lines.append("Signature: " + task.function_definition)

    if task.test_imports:
        lines.append("Test imports:")
        lines.extend(task.test_imports)

    lines.append("Tests (also available as variable TESTS):")
    lines.extend(task.test_list)

    return "\n".join(lines)
