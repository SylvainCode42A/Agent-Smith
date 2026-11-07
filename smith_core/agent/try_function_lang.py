from smith_core.agent.extract import extract_code
from smith_core.agent.formats import (from_python, from_xmlinvoke,
                                      from_hermes, from_react)

if __name__ == "__main__":

    PYTHON_CASES = {
        "bloc fermé": "Thought: ok\n```python\nx = 1\nprint(x)\n```",
        "bloc fermé + <end_code>": "```python\nx = 1\n``` <end_code>",
        "bloc non fermé (stop)": "Thought: ok\n```python\nx = 1\nprint(x)",
        "deux blocs": "```python\na = 1\n```\ntexte\n```python\nb = 2\n```",
        "bloc sans langage": "```\ny = 2\n```",
        "bloc bash": "```bash\nls -la\n```",
        "bloc json": '```json\n{"a": 1}\n```',
        "python + bash": "```bash\nls\n```\n```python\nz = 3\n```",
        "aucun bloc": "Bonjour, je n'ai pas de code.",
        "ouverture seule": "```python\n",
    }

    XML_CASES = {
        "xml simple": '<invoke name="read_file"><parameter name="filepath">'
                      '/testbed/a.py</parameter></invoke>',
        "xml entier": '<invoke name="read_file"><parameter name="filepath">'
                      '/testbed/a.py</parameter><parameter name="start_line">'
                      '1</parameter></invoke>',
        "xml booleen": '<invoke name="run"><parameter name="verbose">true'
                       '</parameter></invoke>',
        "xml quotes simples": "<invoke name='read_file'><parameter "
                              "name='filepath'>a.py</parameter></invoke>",
        "xml sans parametre": '<invoke name="list_files"></invoke>',
        "xml multilign": '<invoke name="write_file"><parameter name="content">'
                         'a = 1\nb = "x"\n</parameter></invoke>',
        "xml deux appels": '<invoke name="a"><parameter name="x">1</parameter>'
                           '</invoke>\n<invoke name="b"><parameter name="y">'
                           'z</parameter></invoke>',
        "xml avec texte autour": 'Thought: je lis\n<invoke name="read_file">'
                                 '<parameter name="filepath">a.py</parameter>'
                                 '</invoke>',
        "xml aucun invoke": "Bonjour, pas de xml.",
        "xml invoke non ferme": '<invoke name="read_file"><parameter '
                                'name="filepath">a.py</parameter>',
        "xml invoke avc param coupe": '<invoke name="read_file"><parameter '
                                'naepath">a.py</parameter></invoke>'
    }

    HERMES_CASES = {
        "hermes simple": '<tool_call>{"name": "read_file", "arguments": '
                         '{"filepath": "a.py"}}</tool_call>',
        "hermes entier": '<tool_call>{"name": "read_file", "arguments": '
                         '{"filepath": "a.py", "start_line": 1}}</tool_call>',
        "hermes booleen": '<tool_call>{"name": "run", "arguments": '
                          '{"verbose": true}}</tool_call>',
        "hermes sans arguments": '<tool_call>{"name": "list_files"}'
                                 '</tool_call>',
        "hermes arguments vide": '<tool_call>{"name": "list_files", '
                                 '"arguments": {}}</tool_call>',
        "hermes multiligne": '<tool_call>\n{\n  "name": "read_file",\n'
                             '  "arguments": {"filepath": "a.py"}\n}\n'
                             '</tool_call>',
        "hermes guillemet dans valeur": '<tool_call>{"name": "write_file", '
                                        '"arguments": {"content": '
                                        '"print(\\"hi\\")"}}</tool_call>',
        "hermes deux appels": '<tool_call>{"name": "a", "arguments": '
                              '{"x": 1}}</tool_call>\n<tool_call>{"name": '
                              '"b", "arguments": {"y": "z"}}</tool_call>',
        "hermes texte autour": 'Thought: je lis\n<tool_call>{"name": '
                               '"read_file", "arguments": {"filepath": '
                               '"a.py"}}</tool_call>',
        "hermes aucun tool_call": "Bonjour, pas de hermes.",
        "hermes json invalide": "<tool_call>{name: read_file}</tool_call>",
        "hermes json liste": "<tool_call>[1, 2]</tool_call>",
        "hermes sans name": '<tool_call>{"arguments": {"x": 1}}</tool_call>',
        "hermes arguments pas objet": '<tool_call>{"name": "a", "arguments": '
                                      '[1, 2]}</tool_call>',
        "hermes valide + invalide": '<tool_call>{"name": "a"}</tool_call>'
                                    '<tool_call>{bad}</tool_call>',
        "hermes non ferme": '<tool_call>{"name": "read_file", "arguments": '
                            '{"filepath": "a.py"}}',
    }

    REACT_CASES = {
        "react simple": 'Action: read_file\nAction Input: '
                        '{"filepath": "a.py"}',
        "react entier": 'Action: read_file\nAction Input: '
                        '{"filepath": "a.py", "start_line": 1}',
        "react booleen": 'Action: run\nAction Input: {"verbose": true}',
        "react input vide": 'Action: list_files\nAction Input: ',
        "react input objet vide": 'Action: list_files\nAction Input: {}',
        "react json multiligne": 'Action: read_file\nAction Input: {\n'
                                 '  "filepath": "a.py",\n  "start_line": 1\n}',
        "react guillemet dans valeur": 'Action: write_file\nAction Input: '
                                       '{"content": "print(\\"hi\\")"}',
        "react avec thought": 'Thought: je dois lire\nAction: read_file\n'
                              'Action Input: {"filepath": "a.py"}',
        "react espaces": 'Action:   read_file  \nAction Input:   '
                         '{"filepath": "a.py"}  \n',
        "react aucun action": "Bonjour, pas de react.",
        "react sans action input": "Action: read_file",
        "react nom invalide": 'Action: 1bad-name\nAction Input: {}',
        "react json invalide": 'Action: read_file\nAction Input: '
                               '{filepath: a.py}',
        "react input liste": 'Action: read_file\nAction Input: [1, 2]',
        "react input chaine": 'Action: read_file\nAction Input: a.py',
        "react texte apres json": 'Action: read_file\nAction Input: '
                                  '{"filepath": "a.py"}\nVoila.',
    }

    EXTRACT_CASES = {
        "python + end_code": "Thought: ok\n```python\nx = 1\n``` <end_code>",
        "python non ferme (stop)": "Thought: ok\n```python\nx = 1\nprint(x)",
        "observation inventee": "```python\na = 1\n```\nObservation: 42\n"
                                "```python\nb = 2\n```",
        "observation en tete": "Observation: 42\n```python\nb = 2\n```",
        "observation dans print": '```python\nprint("Observation: ok")\n```',
        "xml": '<invoke name="read_file"><parameter name="filepath">a.py'
               '</parameter></invoke>',
        "hermes": '<tool_call>{"name": "read_file", "arguments": '
                  '{"filepath": "a.py"}}</tool_call>',
        "react": 'Thought: je lis\nAction: read_file\nAction Input: '
                 '{"filepath": "a.py"}',
        "python prioritaire sur xml": '```python\nx = 1\n```\n<invoke '
                                      'name="f"></invoke>',
        "bloc bash puis hermes": '```bash\nls\n```\n<tool_call>{"name": '
                                 '"ls"}</tool_call>',
        "xml casse puis react": '<invoke name="f"><parameter name="x">1\n'
                                'Action: g\nAction Input: {}',
        "hermes invalide": "<tool_call>{bad}</tool_call>",
        "react sans input": "Action: read_file",
        "bloc json seul": '```json\n{"a": 1}\n```',
        "texte seul": "Bonjour, je n'ai pas de code.",
        "vide": "",
    }

    print("=========== from_python ===========\n")
    for name, text in PYTHON_CASES.items():
        code, notice = from_python(text)
        print(f"--- {name}")
        print(f"code   : {code!r}")
        print(f"notice : {notice!r}\n")

    print("=========== from_xmlinvoke ===========\n")
    for name, text in XML_CASES.items():
        code, notice = from_xmlinvoke(text)
        print(f"--- {name}")
        print(f"code   : {code!r}")
        print(f"notice : {notice!r}\n")

    print("=========== from_hermes ===========\n")
    for name, text in HERMES_CASES.items():
        code, notice = from_hermes(text)
        print(f"--- {name}")
        print(f"code   : {code!r}")
        print(f"notice : {notice!r}\n")

    print("=========== from_react ===========\n")
    for name, text in REACT_CASES.items():
        code, notice = from_react(text)
        print(f"--- {name}")
        print(f"code   : {code!r}")
        print(f"notice : {notice!r}\n")

    print("=========== extract_code ===========\n")
    for name, text in EXTRACT_CASES.items():
        code, notice = extract_code(text)
        print(f"--- {name}")
        print(f"code   : {code!r}")
        print(f"notice : {notice!r}\n")
