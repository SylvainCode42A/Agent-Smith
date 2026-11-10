import ast
import re

KEPT_NODES = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)


def function_name(function_definition: str) -> str | None:
    """Return the name in 'def name(...):', or None if not found."""

    m = re.search(r"def\s+(\w+)\s*\(", function_definition)
    return m.group(1) if m else None


def is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def solution_from_code(code: str, name: str) -> str | None:
    """
    Find the source of function `name` in one executed code block.

    Two shapes are handled:
    - the function is inside a string (solution = "def name(...): ..."),
      which is what the MBPP prompt asks for: that string is returned;
    - the function is defined directly in the block: only the imports and
      top-level def/class are kept (run_tests, print... are dropped).
    """

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    strings = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and f"def {name}(" in n.value and is_valid_python(n.value)]
    if strings:
        return strings[-1]

    if any(isinstance(n, ast.FunctionDef) and n.name == name
           for n in tree.body):
        kept = [ast.get_source_segment(code, n) for n in tree.body
                if isinstance(n, KEPT_NODES)]
        return "\n".join(kept)
    return None


def last_def_solution(steps, function_definition: str) -> str:
    """
    Fallback used when the agent never called final_answer: return the
    most recent code that defines the expected function, or "".
    """

    name = function_name(function_definition)
    if name is None:
        return ""
    for step in reversed(steps):
        solution = solution_from_code(step.sandbox_input, name)
        if solution:
            return solution
    return ""
