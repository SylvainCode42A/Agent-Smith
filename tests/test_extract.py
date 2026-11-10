import pytest
from smith_core.agent.extract import extract_code
from smith_core.agent.formats import (from_python, from_xmlinvoke,
                                      from_hermes, from_react)

# Each case: (id, input text, expected code, expected notice fragment).
# A notice fragment of "" means the notice must be exactly empty.

READ_A = "result = read_file(filepath='a.py')\nprint(result)"
READ_A_L1 = ("result = read_file(filepath='a.py', start_line=1)"
             "\nprint(result)")
RUN_TRUE = "result = run(verbose=True)\nprint(result)"
LIST_FILES = "result = list_files()\nprint(result)"
WRITE_HI = "result = write_file(content='print(\"hi\")')\nprint(result)"
TWO_CALLS = "result = a(x=1)\nprint(result)\nresult = b(y='z')\nprint(result)"


def check(result, expected_code, expected_notice):
    code, notice = result
    assert code == expected_code
    if expected_notice:
        assert expected_notice in notice
    else:
        assert notice == ""


# ---------------------------------------------------------------- python

PYTHON_CASES = [
    ("bloc ferme", "Thought: ok\n```python\nx = 1\nprint(x)\n```",
     "x = 1\nprint(x)", ""),
    ("bloc ferme + end_code", "```python\nx = 1\n``` <end_code>",
     "x = 1", ""),
    ("bloc non ferme", "Thought: ok\n```python\nx = 1\nprint(x)",
     "x = 1\nprint(x)", "not closed"),
    ("deux blocs", "```python\na = 1\n```\ntexte\n```python\nb = 2\n```",
     "a = 1\nb = 2", "2 python blocks"),
    ("bloc sans langage", "```\ny = 2\n```", "y = 2", ""),
    ("bloc bash", "```bash\nls -la\n```", None, "non-Python block(s): bash"),
    ("bloc json", '```json\n{"a": 1}\n```', None,
     "non-Python block(s): json"),
    ("python + bash", "```bash\nls\n```\n```python\nz = 3\n```",
     "z = 3", "non-Python block(s): bash"),
    ("aucun bloc", "Bonjour, je n'ai pas de code.", None, ""),
    ("ouverture seule", "```python\n", None, ""),
]


@pytest.mark.parametrize("text, code, notice",
                         [c[1:] for c in PYTHON_CASES],
                         ids=[c[0] for c in PYTHON_CASES])
def test_from_python(text, code, notice):
    check(from_python(text), code, notice)


# ------------------------------------------------------------------- xml

XML_NOTE = "interpreted your <invoke> XML"

XML_CASES = [
    ("simple", '<invoke name="read_file"><parameter name="filepath">'
     'a.py</parameter></invoke>', READ_A, XML_NOTE),
    ("entier", '<invoke name="read_file"><parameter name="filepath">'
     'a.py</parameter><parameter name="start_line">1</parameter></invoke>',
     READ_A_L1, XML_NOTE),
    ("booleen", '<invoke name="run"><parameter name="verbose">true'
     '</parameter></invoke>', RUN_TRUE, XML_NOTE),
    ("quotes simples", "<invoke name='read_file'><parameter "
     "name='filepath'>a.py</parameter></invoke>", READ_A, XML_NOTE),
    ("sans parametre", '<invoke name="list_files"></invoke>',
     LIST_FILES, XML_NOTE),
    ("multiligne", '<invoke name="write_file"><parameter name="content">'
     'a = 1\nb = "x"\n</parameter></invoke>',
     "result = write_file(content='a = 1\\nb = \"x\"')\nprint(result)",
     XML_NOTE),
    ("deux appels", '<invoke name="a"><parameter name="x">1</parameter>'
     '</invoke>\n<invoke name="b"><parameter name="y">z</parameter>'
     '</invoke>', TWO_CALLS, XML_NOTE),
    ("texte autour", 'Thought: je lis\n<invoke name="read_file">'
     '<parameter name="filepath">a.py</parameter></invoke>',
     READ_A, XML_NOTE),
    ("aucun invoke", "Bonjour, pas de xml.", None, ""),
    ("invoke non ferme", '<invoke name="read_file"><parameter '
     'name="filepath">a.py</parameter>', None, "missing </invoke>"),
    ("parametre casse", '<invoke name="read_file"><parameter '
     'naepath">a.py</parameter></invoke>', None,
     "<parameter> tag in your <invoke> is malformed"),
]


@pytest.mark.parametrize("text, code, notice",
                         [c[1:] for c in XML_CASES],
                         ids=[c[0] for c in XML_CASES])
def test_from_xmlinvoke(text, code, notice):
    check(from_xmlinvoke(text), code, notice)


# ---------------------------------------------------------------- hermes

HERMES_NOTE = "interpreted your <tool_call> JSON"

HERMES_CASES = [
    ("simple", '<tool_call>{"name": "read_file", "arguments": '
     '{"filepath": "a.py"}}</tool_call>', READ_A, HERMES_NOTE),
    ("entier", '<tool_call>{"name": "read_file", "arguments": '
     '{"filepath": "a.py", "start_line": 1}}</tool_call>',
     READ_A_L1, HERMES_NOTE),
    ("booleen", '<tool_call>{"name": "run", "arguments": '
     '{"verbose": true}}</tool_call>', RUN_TRUE, HERMES_NOTE),
    ("sans arguments", '<tool_call>{"name": "list_files"}</tool_call>',
     LIST_FILES, HERMES_NOTE),
    ("arguments vides", '<tool_call>{"name": "list_files", '
     '"arguments": {}}</tool_call>', LIST_FILES, HERMES_NOTE),
    ("multiligne", '<tool_call>\n{\n  "name": "read_file",\n'
     '  "arguments": {"filepath": "a.py"}\n}\n</tool_call>',
     READ_A, HERMES_NOTE),
    ("guillemet dans valeur", '<tool_call>{"name": "write_file", '
     '"arguments": {"content": "print(\\"hi\\")"}}</tool_call>',
     WRITE_HI, HERMES_NOTE),
    ("deux appels", '<tool_call>{"name": "a", "arguments": {"x": 1}}'
     '</tool_call>\n<tool_call>{"name": "b", "arguments": {"y": "z"}}'
     '</tool_call>', TWO_CALLS, HERMES_NOTE),
    ("texte autour", 'Thought: je lis\n<tool_call>{"name": "read_file", '
     '"arguments": {"filepath": "a.py"}}</tool_call>', READ_A, HERMES_NOTE),
    ("aucun tool_call", "Bonjour, pas de hermes.", None, ""),
    ("json invalide", "<tool_call>{name: read_file}</tool_call>",
     None, "JSONDecodeError"),
    ("json liste", "<tool_call>[1, 2]</tool_call>", None, "AttributeError"),
    ("sans name", '<tool_call>{"arguments": {"x": 1}}</tool_call>',
     None, "KeyError('name')"),
    ("arguments pas objet", '<tool_call>{"name": "a", "arguments": '
     '[1, 2]}</tool_call>', None, "arguments must be an object"),
    ("valide + invalide", '<tool_call>{"name": "a"}</tool_call>'
     '<tool_call>{bad}</tool_call>', "result = a()\nprint(result)",
     "Skipped: Error: invalid <tool_call>"),
    ("non ferme", '<tool_call>{"name": "read_file", "arguments": '
     '{"filepath": "a.py"}}', None, ""),
]


@pytest.mark.parametrize("text, code, notice",
                         [c[1:] for c in HERMES_CASES],
                         ids=[c[0] for c in HERMES_CASES])
def test_from_hermes(text, code, notice):
    check(from_hermes(text), code, notice)


# ----------------------------------------------------------------- react

REACT_NOTE = "interpreted your React Action"

REACT_CASES = [
    ("simple", 'Action: read_file\nAction Input: {"filepath": "a.py"}',
     READ_A, REACT_NOTE),
    ("entier", 'Action: read_file\nAction Input: '
     '{"filepath": "a.py", "start_line": 1}', READ_A_L1, REACT_NOTE),
    ("booleen", 'Action: run\nAction Input: {"verbose": true}',
     RUN_TRUE, REACT_NOTE),
    ("input vide", "Action: list_files\nAction Input: ",
     LIST_FILES, REACT_NOTE),
    ("input objet vide", "Action: list_files\nAction Input: {}",
     LIST_FILES, REACT_NOTE),
    ("json multiligne", 'Action: read_file\nAction Input: {\n'
     '  "filepath": "a.py",\n  "start_line": 1\n}', READ_A_L1, REACT_NOTE),
    ("guillemet dans valeur", 'Action: write_file\nAction Input: '
     '{"content": "print(\\"hi\\")"}', WRITE_HI, REACT_NOTE),
    ("avec thought", 'Thought: je dois lire\nAction: read_file\n'
     'Action Input: {"filepath": "a.py"}', READ_A, REACT_NOTE),
    ("espaces", 'Action:   read_file  \nAction Input:   '
     '{"filepath": "a.py"}  \n', READ_A, REACT_NOTE),
    ("aucune action", "Bonjour, pas de react.", None, ""),
    ("sans action input", "Action: read_file", None,
     "not followed by an Action Input"),
    ("nom invalide", "Action: 1bad-name\nAction Input: {}", None,
     "valid Python function name"),
    ("json invalide", "Action: read_file\nAction Input: {filepath: a.py}",
     None, "JSONDecodeError"),
    ("input liste", "Action: read_file\nAction Input: [1, 2]", None,
     "must be a JSON object"),
    ("input chaine", "Action: read_file\nAction Input: a.py", None,
     "JSONDecodeError"),
    ("texte apres json", 'Action: read_file\nAction Input: '
     '{"filepath": "a.py"}\nVoila.', None, "Extra data"),
]


@pytest.mark.parametrize("text, code, notice",
                         [c[1:] for c in REACT_CASES],
                         ids=[c[0] for c in REACT_CASES])
def test_from_react(text, code, notice):
    check(from_react(text), code, notice)


# ---------------------------------------------------------- extract_code

NO_BLOCK = "No valid code block found"

EXTRACT_CASES = [
    ("python + end_code", "Thought: ok\n```python\nx = 1\n``` <end_code>",
     "x = 1", ""),
    ("python non ferme", "Thought: ok\n```python\nx = 1\nprint(x)",
     "x = 1\nprint(x)", "not closed"),
    ("observation inventee", "```python\na = 1\n```\nObservation: 42\n"
     "```python\nb = 2\n```", "a = 1", ""),
    ("observation en tete", "Observation: 42\n```python\nb = 2\n```",
     "b = 2", "started with 'Observation:'"),
    ("observation dans print", '```python\nprint("Observation: ok")\n```',
     'print("Observation: ok")', ""),
    ("xml", '<invoke name="read_file"><parameter name="filepath">a.py'
     '</parameter></invoke>', READ_A, XML_NOTE),
    ("hermes", '<tool_call>{"name": "read_file", "arguments": '
     '{"filepath": "a.py"}}</tool_call>', READ_A, HERMES_NOTE),
    ("react", 'Thought: je lis\nAction: read_file\nAction Input: '
     '{"filepath": "a.py"}', READ_A, REACT_NOTE),
    ("python prioritaire sur xml", '```python\nx = 1\n```\n'
     '<invoke name="f"></invoke>', "x = 1", ""),
    ("bloc bash puis hermes", '```bash\nls\n```\n<tool_call>{"name": '
     '"ls"}</tool_call>', "result = ls()\nprint(result)", HERMES_NOTE),
    ("xml casse puis react", '<invoke name="f"><parameter name="x">1\n'
     'Action: g\nAction Input: {}', "result = g()\nprint(result)",
     "Warning: your <invoke> block is malformed"),
    ("hermes invalide", "<tool_call>{bad}</tool_call>", None, NO_BLOCK),
    ("react sans input", "Action: read_file", None, NO_BLOCK),
    ("bloc json seul", '```json\n{"a": 1}\n```', None, NO_BLOCK),
    ("texte seul", "Bonjour, je n'ai pas de code.", None, NO_BLOCK),
    ("vide", "", None, NO_BLOCK),
]


@pytest.mark.parametrize("text, code, notice",
                         [c[1:] for c in EXTRACT_CASES],
                         ids=[c[0] for c in EXTRACT_CASES])
def test_extract_code(text, code, notice):
    check(extract_code(text), code, notice)


def test_extract_error_downgraded_to_warning_when_code_found():
    # An earlier extractor's "Error:" becomes "Warning:" once a later one
    # succeeds, so the model is not told its turn failed.
    _, notice = extract_code('<invoke name="f">\nAction: g\nAction Input: {}')
    assert "Error:" not in notice
    assert "Warning:" in notice
