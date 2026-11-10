from types import SimpleNamespace

from agent_mbpp.fallback import function_name, last_def_solution

SIGNATURE = "def add(a, b):"


def steps(*codes):
    return [SimpleNamespace(sandbox_input=c) for c in codes]


def test_function_name():
    assert function_name("def similar_elements(t1, t2):") == "similar_elements"
    assert function_name("pas de signature") is None


def test_function_inside_string():
    code = ('import json\n'
            'solution = "def add(a, b):\\n    return a + b"\n'
            'r = run_tests(code=solution, test_list=TESTS)\n'
            'print(r)\n')
    assert (last_def_solution(steps(code), SIGNATURE)
            == "def add(a, b):\n    return a + b")


def test_function_defined_directly_drops_tool_calls():
    code = ("import math\n"
            "def add(a, b):\n"
            "    return a + b\n"
            "print(run_tests(code='x', test_list=TESTS))\n")
    assert (last_def_solution(steps(code), SIGNATURE)
            == "import math\ndef add(a, b):\n    return a + b")


def test_last_step_wins():
    old = 'solution = "def add(a, b):\\n    return 0"'
    new = 'solution = "def add(a, b):\\n    return a + b"'
    assert "a + b" in last_def_solution(steps(old, new), SIGNATURE)


def test_skips_steps_without_the_function():
    good = 'solution = "def add(a, b):\\n    return a + b"'
    assert "a + b" in last_def_solution(steps(good, "", "print(1)"),
                                        SIGNATURE)


def test_ignores_invalid_python():
    broken_block = "def add(a, b):\n    return ("
    broken_string = 'solution = "def add(a, b):\\n    return ("'
    assert last_def_solution(steps(broken_block, broken_string),
                             SIGNATURE) == ""


def test_nothing_found():
    assert last_def_solution(steps("x = 1"), SIGNATURE) == ""
    assert last_def_solution([], SIGNATURE) == ""
