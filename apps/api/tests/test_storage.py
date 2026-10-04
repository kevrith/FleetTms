"""Files in a bucket as well as in a folder: the same behaviour either way, nothing public, nothing lost on the move."""

import secrets

import boto3
import pytest
from moto import mock_aws

from app import http_security, storage, storage_migrate
from app.config import Settings, settings
from tests.shots import fleet, jpeg, upload
from tests.test_data_export import make_export, open_zip

BUCKET = "fleettms-test"
PREFIX = "files"


@pytest.fixture
def bucket(monkeypatch):
    """A bucket (moto's stand-in for S3) with the app pointed at it."""
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", BUCKET)
    monkeypatch.setattr(settings, "s3_region", "us-east-1")
    monkeypatch.setattr(settings, "s3_prefix", PREFIX)
    monkeypatch.setattr(settings, "s3_access_key", secrets.token_hex(8))
    monkeypatch.setattr(settings, "s3_secret_key", secrets.token_hex(16))
    with mock_aws():
        storage.reset_client()
        raw = boto3.client("s3", region_name="us-east-1")
        raw.create_bucket(Bucket=BUCKET)
        yield raw
    storage.reset_client()


def keys_in(raw) -> list[str]:
    return [o["Key"] for o in raw.list_objects_v2(Bucket=BUCKET).get("Contents", [])]


async def test_the_folder_stores_reads_and_removes_files_and_refuses_keys_that_leave_it():
    await storage.save("t/a.txt", b"hello")
    assert await storage.read("t/a.txt") == b"hello" and await storage.exists("t/a.txt")
    assert [c async for c in await storage.stream("t/a.txt")] == [b"hello"]
    assert await storage.delete("t/a.txt") is True and await storage.delete("t/a.txt") is False
    assert await storage.read("t/a.txt") is None and await storage.stream("t/a.txt") is None
    assert await storage.read("../../etc/passwd") is None and await storage.exists("../../etc/passwd") is False


async def test_a_bucket_stores_reads_and_removes_files_under_its_prefix(bucket):
    await storage.save("t/a.txt", b"hello", "text/plain")
    assert keys_in(bucket) == [f"{PREFIX}/t/a.txt"]
    assert bucket.head_object(Bucket=BUCKET, Key=f"{PREFIX}/t/a.txt")["ContentType"] == "text/plain"
    assert await storage.read("t/a.txt") == b"hello" and await storage.exists("t/a.txt")
    assert b"".join([c async for c in await storage.stream("t/a.txt")]) == b"hello"
    assert await storage.delete("t/a.txt") is True and await storage.delete("t/a.txt") is False
    assert keys_in(bucket) == []
    assert await storage.read("t/a.txt") is None and await storage.stream("t/a.txt") is None and not await storage.exists("t/a.txt")


async def test_a_bucket_refuses_keys_that_climb_out_of_the_prefix(bucket):
    assert await storage.read("../other/secret") is None
    assert await storage.exists("a/../../b") is False
    assert await storage.stream("/etc/passwd") is None
    assert await storage.delete("../x") is False
    with pytest.raises(ValueError):
        await storage.save("../x", b"no")


async def test_a_big_file_goes_up_from_disk_and_comes_back_the_same(bucket, tmp_path):
    source = tmp_path / "big.bin"
    source.write_bytes(b"x" * (storage.CHUNK * 3 + 17))
    await storage.save_file("exports/big.bin", source, "application/octet-stream")
    assert await storage.read("exports/big.bin") == source.read_bytes()
    pieces = [c async for c in await storage.stream("exports/big.bin")]
    assert len(pieces) == 4 and b"".join(pieces) == source.read_bytes()  # sent a piece at a time, not all in memory


async def test_serving_a_file_from_a_bucket_carries_its_type_and_the_download_name(bucket):
    await storage.save("t/a.zip", b"data")
    response = await storage.serve("t/a.zip", "application/zip", filename="copy.zip", headers={"Cache-Control": "private, no-store"})
    assert response.media_type == "application/zip" and response.headers["content-disposition"] == 'attachment; filename="copy.zip"'
    assert response.headers["cache-control"] == "private, no-store"
    assert await storage.serve("t/missing.zip", "application/zip") is None


async def test_photos_go_to_the_bucket_and_are_viewed_through_the_same_signed_links(client, bucket):
    f = await fleet(client)
    data = jpeg()
    res = await upload(client, f.owner, data=data)
    assert res.status_code == 201, res.text
    stored = [k for k in keys_in(bucket) if k.endswith(".jpg")]
    assert len(stored) == 1 and stored[0].startswith(f"{PREFIX}/")
    assert bucket.head_object(Bucket=BUCKET, Key=stored[0])["ContentType"] == "image/jpeg"
    assert not (storage._root() / stored[0].removeprefix(f"{PREFIX}/")).exists()  # nothing was left on disk
    served = await client.get(res.json()["url"])
    assert served.status_code == 200 and served.content == data
    assert served.headers["content-type"] == "image/jpeg" and served.headers["cache-control"] == "private, no-store"
    assert (await client.get("/media/not-a-token")).status_code == 404
    assert (await client.get(storage.signed_url("../../etc/passwd"))).status_code == 404
    assert (await client.get(storage.signed_url("missing/photo.jpg"))).status_code == 404  # a genuine link to a file that is not there


async def test_a_data_copy_with_photos_is_built_stored_in_the_bucket_downloaded_and_deleted_there(client, bucket):
    from sqlalchemy import select

    from app import data_export
    from app.models import DataExport
    from tests.leasing import in_db

    f = await fleet(client)
    data = jpeg()
    assert (await upload(client, f.owner, data=data)).status_code == 201
    export = await make_export(client, f.owner, include_photos=True)
    assert export["status"] == "ready"
    assert any(k.startswith(f"{PREFIX}/exports/") and k.endswith(".zip") for k in keys_in(bucket))
    z = await open_zip(client, f.owner, export)
    photos = [n for n in z.namelist() if n.startswith("photos/")]
    assert len(photos) == 1 and z.read(photos[0]) == data
    assert "manifest.json" in z.namelist()

    async def expire(db):
        e = (await db.execute(select(DataExport))).scalar_one()
        e.expires_at = e.created_at
        return e.storage_key

    key = await in_db(expire)
    assert await data_export.purge_expired() == 1
    assert not await storage.exists(key) and not [k for k in keys_in(bucket) if "exports/" in k]


async def test_ready_says_whether_files_can_be_stored_and_read_back(client, bucket, monkeypatch):
    from tests.test_monitoring import worker_alive

    await worker_alive()
    ok = (await client.get("/ready")).json()
    assert ok["ready"] is True and ok["checks"]["storage"] == {"ok": True, "backend": "s3"}
    assert keys_in(bucket) == []  # the test file is removed again
    bucket.delete_bucket(Bucket=BUCKET)
    down = await client.get("/ready")
    assert down.status_code == 503 and "storage" in down.json()["failing"]
    assert "files cannot be stored or read" in down.json()["checks"]["storage"]["reason"]
    assert settings.s3_secret_key not in down.text


async def test_a_bucket_backend_without_a_bucket_name_is_a_configuration_problem(monkeypatch):
    assert storage.config_problem() is None
    monkeypatch.setattr(settings, "storage_backend", "s3")
    assert storage.config_problem() == "STORAGE_BACKEND=s3 needs S3_BUCKET."
    monkeypatch.setattr(settings, "storage_backend", "ftp")
    assert storage.config_problem() == "STORAGE_BACKEND must be local or s3."
    result = await storage.probe()
    assert result["ok"] is False and "STORAGE_BACKEND" in result["error"]


def test_production_will_not_start_with_a_bucket_backend_that_has_no_bucket():
    from tests.test_rate_limits import GOOD

    ok = http_security.production_problems(Settings.model_construct(**GOOD), sms_is_stand_in=False)
    assert not any("S3_BUCKET" in p for p in ok)
    bad = http_security.production_problems(Settings.model_construct(**{**GOOD, "storage_backend": "s3", "s3_bucket": ""}), sms_is_stand_in=False)
    assert any("S3_BUCKET" in p for p in bad)


async def test_moving_the_folder_to_the_bucket_is_checked_repeatable_and_removes_only_what_arrived(bucket, tmp_path, monkeypatch):
    root = tmp_path / "old-media"
    (root / "b1/odometer").mkdir(parents=True)
    (root / "exports/b1").mkdir(parents=True)
    (root / "b1/odometer/a.jpg").write_bytes(b"photo-a")
    (root / "b1/odometer/b.jpg").write_bytes(b"photo-b")
    (root / "exports/b1/e.zip").write_bytes(b"zip")
    log: list[str] = []

    dry = await storage_migrate.migrate(dry_run=True, root=root, out=log.append)
    assert dry == {"moved": 0, "already_there": 0, "removed_locally": 0, "failed": 0} and keys_in(bucket) == [] and len(log) == 3

    first = await storage_migrate.migrate(root=root)
    assert first["moved"] == 3 and first["failed"] == 0
    assert sorted(keys_in(bucket)) == [f"{PREFIX}/b1/odometer/a.jpg", f"{PREFIX}/b1/odometer/b.jpg", f"{PREFIX}/exports/b1/e.zip"]
    assert await storage.read("b1/odometer/a.jpg") == b"photo-a"
    assert (root / "b1/odometer/a.jpg").exists()  # nothing is removed unless asked

    (root / "b1/odometer/b.jpg").write_bytes(b"photo-b-changed")  # a file that differs is sent again; one that matches is not
    again = await storage_migrate.migrate(root=root, delete_local=True)
    assert again["already_there"] == 2 and again["moved"] == 1 and again["removed_locally"] == 3
    assert await storage.read("b1/odometer/b.jpg") == b"photo-b-changed"
    assert not [p for p in root.rglob("*") if p.is_file()]


async def test_a_file_that_cannot_be_sent_is_reported_and_stays_where_it_is(bucket, tmp_path, monkeypatch):
    root = tmp_path / "old-media"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"a")
    (root / "b.jpg").write_bytes(b"b")
    real = storage.save

    async def flaky(key, data, content_type=None):
        if key == "a.jpg":
            raise OSError("network down")
        await real(key, data, content_type)

    monkeypatch.setattr(storage, "save", flaky)
    log: list[str] = []
    result = await storage_migrate.migrate(root=root, delete_local=True, out=log.append)
    assert result == {"moved": 1, "already_there": 0, "removed_locally": 1, "failed": 1}
    assert (root / "a.jpg").exists() and not (root / "b.jpg").exists() and log == ["FAILED a.jpg: OSError"]


async def test_the_move_refuses_to_run_while_the_app_still_points_at_the_folder(tmp_path):
    with pytest.raises(SystemExit):
        await storage_migrate.migrate(root=tmp_path)
