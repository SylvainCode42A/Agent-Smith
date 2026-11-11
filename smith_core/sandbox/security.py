"""Security rules applied to LLM-generated code inside the sandbox."""
import builtins
import types
import ast
import os
import sys

BLOCKED_BUILTINS = {
    "eval", "exec", "compile",
    "input", "breakpoint",
    "globals", "locals", "vars",
    "help", "exit", "quit",
    "copyright", "credits", "license",
}

BLOCKED_EVENTS = ("socket.", "subprocess.", "os.system", "os.exec",
                "os.spawn", "os.posix_spawn", "os.fork", "os.forkpty",
                "os.kill", "os.killpg", "pty.spawn", "ctypes.")

WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


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


def build_safe_builtins(allowed_imports: list[str],
                        allowed_dirs: list[str]) -> dict:
    """Copy of the builtins with dangerous entries removed or replaced."""
    safe = dict(builtins.__dict__)

    for nom in BLOCKED_BUILTINS:
        if nom in safe:
            safe.pop(nom, None)

    safe["__import__"] = make_guarded_import(allowed_imports)
    safe["getattr"] = safe_getattr
    safe["open"] = make_safe_open(allowed_dirs)
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


def is_path_allowed(path: str, allowed_dirs: list[str]) -> bool:
    """True if `path` is inside one of the allowed directories."""
    real = os.path.realpath(path)
    for directory in allowed_dirs:
        base = os.path.realpath(directory)

        if real == base or real.startswith(f"{base}{os.sep}"):
            return True
    return False


def make_safe_open(allowed_dirs: list[str]):
    """Build an open() replacement limited to the allowed directories."""
    real_open = builtins.open

    def safe_open(file, mode="r", *args, **kwargs):
        if isinstance(file, int):
            raise PermissionError("Opening file descriptors is not allowed")
        if not is_path_allowed(file, allowed_dirs):
            raise PermissionError(
                f"Access to '{file}' is not allowed. "
                f"Allowed directories: {', '.join(allowed_dirs)}")
        return real_open(file, mode, *args, **kwargs)

    return safe_open

def _is_read_only(mode, flags) -> bool:
    """True if an 'open' audit event only reads the file."""
    if isinstance(mode, str):
        return not any(c in mode for c in "wax+")
    return not (flags or 0) & WRITE_FLAGS


def make_audit_hook(allowed_dirs: list[str]):
    """Build the hook that blocks files, network and processes."""
    python_dirs = [sys.prefix, sys.base_prefix, sys.exec_prefix]

    def hook(event, args):
        if event == "open":
            path, mode, flags = args
            if path is None or isinstance(path, int):
                return
            path = os.fsdecode(path)
            if is_path_allowed(path, allowed_dirs):
                return
            if _is_read_only(mode, flags) and is_path_allowed(path, python_dirs):
                return
            raise PermissionError(f"Access to '{path}' is not allowed")

        if event.startswith(BLOCKED_EVENTS):
            raise PermissionError(f"'{event}' is not allowed in the sandbox")

    return hook
