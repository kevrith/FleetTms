"""Moves the files already in the media folder into the bucket: `python -m app.storage_migrate [--dry-run] [--delete-local]`.

Run it once, after setting STORAGE_BACKEND=s3 and the bucket settings. It is safe to run again: a file that is already in the bucket
with the same size is skipped, and a file is only removed from the folder (with --delete-local) after it has been read back from the
bucket and found identical. Run it before switching traffic to the new setting, or straight after: photos not yet moved show as
missing until it has run.
"""

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

from app import storage
from app.config import settings


def local_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


async def migrate(*, dry_run: bool = False, delete_local: bool = False, root: Path | None = None, out=print) -> dict:
    problem = storage.config_problem()
    if problem or not storage.uses_bucket():
        raise SystemExit(problem or "Set STORAGE_BACKEND=s3 (and the bucket settings) first: there is nowhere to move the files to.")
    root = root or storage._root()
    result = {"moved": 0, "already_there": 0, "removed_locally": 0, "failed": 0}
    for path in local_files(root):
        key = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
            existing = await storage.read(key)
            if existing is not None and hashlib.sha256(existing).digest() == hashlib.sha256(data).digest():
                result["already_there"] += 1
            elif dry_run:
                out(f"would move {key}")
                continue
            else:
                await storage.save(key, data)
                if await storage.read(key) != data:  # read back: never trust a write
                    raise OSError("the file read back from the bucket is not the one that was sent")
                result["moved"] += 1
            if delete_local and not dry_run:
                path.unlink()
                result["removed_locally"] += 1
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the rest; it is reported and the run exits non-zero
            result["failed"] += 1
            out(f"FAILED {key}: {type(e).__name__}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="list what would be moved, change nothing")
    parser.add_argument("--delete-local", action="store_true", help="remove each file from the folder once it is safely in the bucket")
    args = parser.parse_args()
    result = asyncio.run(migrate(dry_run=args.dry_run, delete_local=args.delete_local))
    print(f"Bucket {settings.s3_bucket}: {result['moved']} moved, {result['already_there']} already there, {result['removed_locally']} removed from the folder, {result['failed']} failed.")
    sys.exit(1 if result["failed"] else 0)


if __name__ == "__main__":
    main()
