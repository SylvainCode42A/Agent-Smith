"""Security rules applied to LLM-generated code inside the sandbox."""
import builtins
import types
import ast

BLOCKED_BUILTINS = {
    "eval", "exec", "compile",
    "open",
    "input", "breakpoint",
    "globals", "locals", "vars",
    "help", "exit", "quit",
    "copyright", "credits", "license",
}


def is_import_allowed(name: str, allowed: list[str]) -> bool:
    """Return True if module `name` matches an entry of the allowlist.

    An entry "pkg" allows only "pkg".
    An entry "pkg.*" allows "pkg" and every submodule "pkg.xxx".
    """
    for entry in allowed:
        if entry.endswith(".*"):
            base = entry[:-2]
            if name == base or name.startswith(base + "."):
                return True
        elif name == entry:
            return True
    return False


def _refuse(name: str, allowed: list[str]) -> ImportError:
    """Build the error message shown to the LLM."""
    return ImportError(f"Import of '{name}' is not allowed. "
                    f"Allowed imports: {', '.join(allowed)}")


def make_guarded_import(allowed: list[str]):
    """Build an __import__ replacement that only lets allowed modules in."""
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None,
                    fromlist=(), level=0):
        if level != 0:
            raise ImportError("Relative imports are not allowed")

        if not is_import_allowed(name, allowed):
            raise _refuse(name, allowed)

        module = real_import(name, globals, locals, fromlist, level)

        for item in fromlist or ():
            value = getattr(module, item, None)
            full_name = f"{name}.{item}"
            if (isinstance(value, types.ModuleType)
                    and not is_import_allowed(full_name, allowed)):
                raise _refuse(full_name, allowed)

        return module

    return guarded_import


def build_safe_builtins(allowed_imports: list[str]) -> dict:
    """Copy of the builtins with dangerous entries removed or replaced."""
    safe = dict(builtins.__dict__)

    for nom in BLOCKED_BUILTINS:
        if nom in safe:
            safe.pop(nom, None)

    safe["__import__"] = make_guarded_import(allowed_imports)
    safe["getattr"] = safe_getattr
    return safe


def _is_dunder(name: str) -> bool:
    """True for names like __class__, __globals__, __subclasses__."""
    if name.startswith("__") and name.endswith("__"):
        return True
    return False


def safe_getattr(obj, name, *default):
    """getattr that refuses dunder attributes."""
    if _is_dunder(name):
        raise AttributeError(f"Access to '{name}' is not allowed")
    return getattr(obj, name, *default)


class SecurityError(Exception):
    """Raised when the code uses a forbidden construct."""


ALLOWED_DUNDER_NAMES = {"__name__", "__import__"}


def check_ast(code: str) -> None:
    """Refuse dunder attributes and names before the code runs."""
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_dunder(node.attr):
            raise SecurityError(
                f"Access to attribute '{node.attr}' is not allowed")
        if (isinstance(node, ast.Name) and _is_dunder(node.id)
                and node.id not in ALLOWED_DUNDER_NAMES):
            raise SecurityError(f"Use of name '{node.id}' is not allowed")
