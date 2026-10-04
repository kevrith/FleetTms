"""The production image installs requirements.txt and nothing else. Anything the app imports must therefore be listed there, not only in the
development requirements: that mistake once left a production image that could not start (httpx)."""

import ast
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
# What an import is called, when it is not what the package is called.
PACKAGE_OF = {"jwt": "pyjwt", "PIL": "pillow", "multipart": "python-multipart", "pydantic_settings": "pydantic-settings", "argon2": "argon2-cffi", "email_validator": "email-validator", "starlette": "fastapi", "pydantic": "fastapi"}


def listed() -> set[str]:
    names = set()
    for line in (API_DIR / "requirements.txt").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-")):
            names.add(line.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip().lower())
    return names


def test_everything_the_app_imports_is_in_the_production_requirements():
    missing = {}
    for path in (API_DIR / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else [node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else []
            for module in modules:
                if module not in sys.stdlib_module_names and module != "app" and PACKAGE_OF.get(module, module).lower() not in listed():
                    missing.setdefault(module, path.name)
    assert missing == {}, f"imported by the app but not in requirements.txt: {missing}"


def test_the_pinned_versions_cover_every_requirement():
    pinned = {line.split("==")[0].strip().lower().replace("_", "-") for line in (API_DIR / "constraints.txt").read_text().splitlines() if "==" in line}
    gaps = {name.replace("_", "-") for name in listed()} - pinned
    assert gaps == set(), f"in requirements.txt but not pinned in constraints.txt: {gaps}"
