"""Security rules applied to LLM-generated code inside the sandbox."""
import builtins
import types


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