"""Build the text manual describing the sandbox functions to the LLM."""
from smith_core.models import SandboxConfig

JSON_TO_PY = {"string": "str", "integer": "int", "number": "float",
            "boolean": "bool", "array": "list", "object": "dict"}


def tool_signature(tool) -> str:
    """'run_tests(code: str, test_list: list) -> str' from an MCP tool."""
    props = tool.inputSchema.get("properties", {})
    required = tool.inputSchema.get("required", [])
    parts = []
    for name, prop in props.items():
        if name in required:
            py_type = JSON_TO_PY.get(prop.get("type"), "Any")
            parts.append(f"{name}: {py_type}")
    for name, prop in props.items():
        if name not in required:
            py_type = JSON_TO_PY.get(prop.get("type"), "Any")
            parts.append(f"{name}: {py_type} = None")
    return f"{tool.name}({', '.join(parts)}) -> str"


def first_line(text: str) -> str:
    """First non-empty line of a docstring (keeps the manual short)."""
    for line in text.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def build_manual(tools: list, config: SandboxConfig) -> str:
    """Full manual: one entry per MCP tool, final_answer, and the rules."""
    lines = ["Available functions (call them directly in your Python code):"]
    for tool in tools:
        lines.append(f"- {tool_signature(tool)}")
        lines.append(f"    {first_line(tool.description or '')}")
    lines.append("- final_answer(answer: str) -> None")
    lines.append("    Submit your final answer and stop.")
    lines.append("")
    lines.append("Always print() the values you want to see.")
    lines.append(f"Allowed import : {', '.join(config.authorized_imports)}")
    return "\n".join(lines)
