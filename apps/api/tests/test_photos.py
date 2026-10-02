import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image, ImageDraw

from app import storage
from tests.helpers import bearer, owner_session
from tests.shots import jpeg, now_iso, upload


async def test_upload_returns_a_short_lived_link_that_serves_the_same_bytes(client):
    owner, _ = await owner_session(client)
    data = jpeg()
    res = await upload(client, owner, data=data)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "odometer" and body["lat"] == pytest.approx(-1.29)
    served = await client.get(body["url"])
    assert served.status_code == 200 and served.content == data
    assert served.headers["cache-control"] == "private, no-store"
    assert served.headers["content-type"] == "image/jpeg"


async def test_links_cannot_be_forged_altered_or_used_after_expiry(client):
    owner, _ = await owner_session(client)
    url = (await upload(client, owner)).json()["url"]
    token = url.rsplit("/", 1)[1]
    encoded, expires, sig = token.split(".")
    assert (await client.get(f"/media/{encoded}.{int(expires) + 99999}.{sig}")).status_code == 404  # longer expiry
    assert (await client.get(f"/media/{encoded}.{expires}.{sig[:-2]}xx")).status_code == 404  # wrong signature
    assert (await client.get("/media/not-a-token")).status_code == 404
    other_key = storage.signed_url("../../etc/passwd")  # a genuine signature over a path outside storage
    assert (await client.get(other_key)).status_code == 404
    key = storage.key_from_token(token)
    assert (await client.get(storage.signed_url(key, seconds=-5))).status_code == 404  # expired


async def test_stale_future_and_missing_capture_times_are_rejected(client):
    owner, _ = await owner_session(client)
    stale = await upload(client, owner, captured_at=now_iso(minutes_ago=30))
    assert stale.status_code == 422 and stale.json()["detail"]["code"] == "photo_not_fresh"
    future = await upload(client, owner, captured_at=(datetime.now(UTC) + timedelta(hours=2)).isoformat())
    assert future.json()["detail"]["code"] == "photo_not_fresh"
    missing = await upload(client, owner, captured_at=None)
    assert missing.json()["detail"]["code"] == "captured_at_required"
    skewed = await upload(client, owner, captured_at=(datetime.now(UTC) + timedelta(minutes=2)).isoformat())
    assert skewed.status_code == 201  # a phone clock a little ahead is fine


async def test_bad_files_are_rejected(client):
    owner, _ = await owner_session(client)
    not_image = await upload(client, owner, data=b"this is not a photo")
    assert not_image.json()["detail"]["code"] == "not_an_image"
    tiny = await upload(client, owner, data=jpeg(size=(200, 150)))
    assert tiny.json()["detail"]["code"] == "photo_quality"
    blank = io.BytesIO()
    Image.new("RGB", (640, 480), (0, 0, 0)).save(blank, "JPEG")
    assert (await upload(client, owner, data=blank.getvalue())).json()["detail"]["code"] == "photo_blank"
    white = io.BytesIO()
    Image.new("RGB", (640, 480), (255, 255, 255)).save(white, "JPEG")
    assert (await upload(client, owner, data=white.getvalue())).json()["detail"]["code"] == "photo_blank"
    # A black frame with a bit of text on it (what a covered lens plus a timestamp overlay looks like) is still blank.
    stamped = Image.new("RGB", (640, 480), (0, 0, 0))
    ImageDraw.Draw(stamped).text((20, 400), "02.10.26 09:53:18", fill=(255, 255, 0))
    buf = io.BytesIO()
    stamped.save(buf, "JPEG")
    assert (await upload(client, owner, data=buf.getvalue())).json()["detail"]["code"] == "photo_blank"
    bad_location = await upload(client, owner, lat=95)
    assert bad_location.json()["detail"]["code"] == "invalid_location"


async def test_the_same_photo_cannot_be_uploaded_twice(client):
    owner, _ = await owner_session(client)
    data = jpeg()
    assert (await upload(client, owner, data=data)).status_code == 201
    again = await upload(client, owner, data=data)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "duplicate_photo"


async def test_web_uploads_are_judged_by_the_photos_own_capture_time(client):
    owner, _ = await owner_session(client)
    fresh = await upload(client, owner, source="web", captured_at=None, data=jpeg(taken=datetime.now(UTC)))
    assert fresh.status_code == 201 and fresh.json()["source"] == "web"
    old = await upload(client, owner, source="web", captured_at=None, data=jpeg(taken=datetime.now(UTC) - timedelta(hours=3)))
    assert old.json()["detail"]["code"] == "photo_not_fresh"
    no_exif = await upload(client, owner, source="web", captured_at=None, data=jpeg())
    assert no_exif.json()["detail"]["code"] == "photo_not_fresh"
    # A browser cannot talk its way past this by claiming a capture time.
    claimed = await upload(client, owner, source="web", captured_at=now_iso(), data=jpeg())
    assert claimed.json()["detail"]["code"] == "photo_not_fresh"


async def test_uploading_needs_a_signed_in_user_with_trip_access(client):
    from tests.helpers import staff_session

    assert (await client.post("/photos", data={"kind": "odometer", "source": "camera"}, files={"file": ("a.jpg", jpeg(), "image/jpeg")})).status_code == 401
    owner, _ = await owner_session(client)
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await upload(client, accountant)).status_code == 403
    assert (await upload(client, owner)).status_code == 201
    assert bearer(owner)  # owners hold trips.manage
