"""Whether the phone app's native side has changed since a given commit, so an over-the-air update (which carries only JavaScript) would
not be safe to send to the apps already installed.

    python3 scripts/mobile/native_changed.py <commit the installed app was built from>

Exit 0: nothing native changed, an over-the-air update is safe. Exit 1: something did (said on stderr), so a new APK must be built first.
Exit 2: the commit could not be read. It is deliberately cautious: any dependency, app.json or app.config.js change counts, even one that
would have been harmless, because a wrong "safe" crashes drivers' phones and a wrong "unsafe" only costs one build."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys

PATHS = ("apps/mobile/package.json", "apps/mobile/app.json", "apps/mobile/app.config.js")


def read_at(commit: str | None, path: str) -> str:
    if commit is None:
        with open(path, encoding="utf-8") as f:
            return f.read()
    return subprocess.run(["git", "show", f"{commit}:{path}"], check=True, capture_output=True, text=True).stdout


def native_facts(read) -> dict:
    package = json.loads(read("apps/mobile/package.json"))
    return {
        "dependencies": {k: v for k, v in package.get("dependencies", {}).items() if not k.startswith("@fleettms/")},
        "app.json": json.loads(read("apps/mobile/app.json")),
        "app.config.js": hashlib.sha256(read("apps/mobile/app.config.js").encode()).hexdigest(),
    }


def differences(old: dict, new: dict) -> list[str]:
    out = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) == new.get(key):
            continue
        if key == "dependencies":
            a, b = old[key], new[key]
            out += [f"dependency {name}: {a.get(name)} -> {b.get(name)}" for name in sorted(set(a) | set(b)) if a.get(name) != b.get(name)]
        else:
            out.append(f"{key} changed")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        old = native_facts(lambda p: read_at(argv[1], p))
    except (subprocess.CalledProcessError, OSError, ValueError):
        print(f"Could not read the app's files at commit {argv[1]}.", file=sys.stderr)
        return 2
    changed = differences(old, native_facts(lambda p: read_at(None, p)))
    for line in changed:
        print(line, file=sys.stderr)
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
