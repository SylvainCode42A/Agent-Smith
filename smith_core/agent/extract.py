import re
from smith_core.agent.formats import (from_python, from_xmlinvoke,
                                      from_hermes, from_react)


EXTRACTORS = [from_python, from_xmlinvoke, from_hermes, from_react]
END_CODE = "<end_code>"
NO_BLOCK_MSG = ("No valid code block found. Answer with"
                " Thought: then a ```python block ending with <end_code>.")


def extract_code(text: str) -> tuple[str | None, str]:
    notices = []
    parts = re.split(r"^Observation:", text, maxsplit=1, flags=re.MULTILINE)
    text = parts[0]
    if not text.strip() and len(parts) > 1:
        text = parts[1]
        notices.append("Note: your answer started with 'Observation:'; "
                       "never write it yourself.")
    text = text.replace(END_CODE, "")

    for extractor in EXTRACTORS:
        (code, notice) = extractor(text)
        if notice:
            notices.append(notice)
        if code:
            notices = [n.replace("Error:", "Warning:", 1) for n in notices]
            return code, " ".join(notices)

    notices.append(NO_BLOCK_MSG)
    return None, " ".join(notices)
