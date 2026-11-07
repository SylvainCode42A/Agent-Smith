import re
import json
from smith_core.agent.helpers import call_to_python, parse_value

# closed/ opened block regex, for all languages (from_python)
ANY_BLOCK = re.compile(r"```([\w+-]*)[ \t]*\n(.*?)```", re.DOTALL)
PY_OPEN = re.compile(r"```(?:python|py)[ \t]*\n")

# regex for xml, flag the defferent group's (1 = functions, 2 = corpus)
# and apply structure inside the corpus
INVOKE = re.compile(r"<invoke\s+name=[\"']([^\"']+)[\"']\s*>(.*?)</invoke>",
                    re.DOTALL)
PARAM = re.compile(r"<parameter\s+name=[\"']([^\"']+)[\"']\s*>(.*?)"
                   "</parameter>", re.DOTALL)

# regex for Hermes languages
HERMES = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)

# regex for REACT languages
REACT = re.compile(r"Action:\s*([A-Za-z_]\w*)\s*\nAction Input:\s*(.*)",
                   re.DOTALL)


def from_python(text: str) -> tuple[str | None, str]:
    blocks, skipped = [], set()
    for m in ANY_BLOCK.finditer(text):
        lang = m.group(1).lower()
        if lang in ("", "python", "py"):
            blocks.append(m.group(2))
        else:
            skipped.add(lang)

    if blocks:
        notice = []
        if len(blocks) > 1:
            notice.append(f"Note: {len(blocks)} python blocks found;"
                          " I executed them all.")
        if skipped:
            notice.append("Note: ignored non-Python block(s): "
                          f"{', '.join(sorted(skipped))}.")
        return "\n".join(b.strip("\n") for b in blocks), " ".join(notice)

    m = PY_OPEN.search(text)
    if m and text[m.end():].strip():
        return (text[m.end():].strip("\n"),
                "Note: your code block was not closed;"
                " I executed everything after ```python.")
    if skipped:
        return None, ("Ignored non-Python block(s): "
                      f"{', '.join(sorted(skipped))}.")
    return None, ""


def from_xmlinvoke(text: str) -> tuple[str | None, str]:
    calls = []
    for m in INVOKE.finditer(text):
        params = PARAM.findall(m.group(2))
        if m.group(2).count("<parameter") != len(params):
            return None, ("Error: a <parameter> tag in your <invoke> "
                          "is malformed, this <invoke> was ignored.")
        args = {k: parse_value(v) for k, v in PARAM.findall(m.group(2))}
        calls.append(call_to_python(m.group(1), args))
    if not calls:
        if "<invoke" in text:
            return None, ("Error: your <invoke> block is malformed "
                          "(missing </invoke>), this <invoke> was ignored.")
        return None, ""
    return "\n".join(calls), ("Note: interpreted your <invoke> XML"
                              " as a Python tool call.")


def from_hermes(text: str) -> tuple[str | None, str]:
    calls, errors = [], []
    for m in HERMES.finditer(text):
        try:
            data = json.loads(m.group(1))
            args = data.get("arguments", {})
            if not isinstance(args, dict):
                raise TypeError("arguments must be an object")
            calls.append(call_to_python(data["name"], args))
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            errors.append(f"Error: invalid <tool_call> ({e!r}).")

    if calls:
        notice = ("Note: interpreted your <tool_call> JSON"
                  " as a Python tool call.")
        if errors:
            notice += " Skipped: " + " ".join(errors)
        return "\n".join(calls), notice
    if errors:
        return None, " ".join(errors)
    return None, ""


def from_react(text: str) -> tuple[str | None, str]:
    m = REACT.search(text)
    if not m:
        if "Action:" not in text:
            return None, ""
        if "Action Input:" not in text:
            return None, ("Error: your Action: is not followed by an "
                          "Action Input: line with a JSON object.")
        return None, ("Error: the name after Action: must be a valid "
                      "Python function name (letters, digits, _).")

    name, raw = m.group(1), m.group(2).strip()
    try:
        args = json.loads(raw) if raw else {}
        if not isinstance(args, dict):
            raise TypeError("Action Input must be a JSON object")
    except (ValueError, TypeError) as e:
        return None, f"Error: invalid React Action Input for {name} ({e!r})."
    return call_to_python(name, args), ("Note: interpreted your React "
                                        "Action as a Python tool call.")
