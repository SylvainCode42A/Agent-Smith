import json


def call_to_python(name: str, args: dict) -> str:
    kwargs = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"result = {name}({kwargs})\nprint(result)"


def parse_value(raw: str):
    raw = raw.strip()
    try:
        return json.loads(raw)
    except ValueError:
        return raw
