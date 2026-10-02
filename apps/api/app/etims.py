"""Talking to KRA eTIMS (OSCU). With `ETIMS_BASE_URL` empty a stand-in is used, so nothing leaves the machine in
development. The device's communication key is fetched when needed and kept in memory only: nothing secret is stored."""

import logging
from dataclasses import dataclass
from typing import ClassVar, Protocol

import httpx

from app.config import settings

log = logging.getLogger(__name__)


class EtimsTransient(Exception):
    """KRA could not be reached or had a problem of its own. Trying again later may work."""


class EtimsRejected(Exception):
    """KRA looked at the invoice and refused it. Trying the same thing again will not help: a person must fix it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{message} (KRA code {code})")
        self.code, self.message = code, message


@dataclass(frozen=True)
class Device:
    tin: str
    branch_id: str
    serial: str


@dataclass(frozen=True)
class Receipt:
    receipt_no: str
    sdc_id: str | None
    sdc_time: str | None
    signature: str | None
    internal_data: str | None


class EtimsClient(Protocol):
    async def connect(self, device: Device) -> None: ...

    async def register_item(self, device: Device, item: dict) -> None: ...

    async def submit_sale(self, device: Device, body: dict) -> Receipt: ...


class FakeEtims:
    """Keeps what would have been sent, and fails on request, so tests and local development can see every outcome."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.items: list[dict] = []
        self.connected: list[Device] = []
        self.script: list[Exception] = []  # raised one per call, oldest first

    def reset(self) -> None:
        self.sent.clear(), self.items.clear(), self.connected.clear(), self.script.clear()

    def _maybe_fail(self) -> None:
        if self.script:
            raise self.script.pop(0)

    async def connect(self, device: Device) -> None:
        self._maybe_fail()
        self.connected.append(device)

    async def register_item(self, device: Device, item: dict) -> None:
        self._maybe_fail()
        self.items.append(item)

    async def submit_sale(self, device: Device, body: dict) -> Receipt:
        self._maybe_fail()
        self.sent.append(body)
        n = len(self.sent)
        return Receipt(receipt_no=str(1000 + n), sdc_id=f"SDC{device.serial[-6:]}", sdc_time=body["cfmDt"], signature=f"SIGN{n:08d}", internal_data=f"INTL{n:08d}")


class OscuClient:
    """KRA's online sales control unit interface."""

    _keys: ClassVar[dict[Device, str]] = {}  # in memory only

    def __init__(self) -> None:
        self.base = settings.etims_base_url.rstrip("/")

    async def _call(self, path: str, body: dict, headers: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                res = await http.post(f"{self.base}{path}", json=body, headers=headers or {})
        except httpx.HTTPError as e:
            raise EtimsTransient(f"Could not reach KRA: {type(e).__name__}") from e
        if res.status_code >= 500:
            raise EtimsTransient(f"KRA had a problem (HTTP {res.status_code}).")
        try:
            data = res.json()
        except ValueError:
            raise EtimsTransient("KRA sent something unreadable.") from None
        if str(data.get("resultCd")) != "000":
            raise EtimsRejected(str(data.get("resultCd")), str(data.get("resultMsg") or "KRA refused the request"))
        return data

    async def _headers(self, device: Device) -> dict:
        if device not in self._keys:
            data = await self._call("/selectInitOsdcInfo", {"tin": device.tin, "bhfId": device.branch_id, "dvcSrlNo": device.serial})
            key = ((data.get("data") or {}).get("info") or {}).get("cmcKey")
            if not key:
                raise EtimsRejected("none", "KRA did not return a communication key for this device")
            self._keys[device] = key
        return {"tin": device.tin, "bhfId": device.branch_id, "cmcKey": self._keys[device]}

    async def connect(self, device: Device) -> None:
        self._keys.pop(device, None)
        await self._headers(device)

    async def register_item(self, device: Device, item: dict) -> None:
        await self._call("/saveItems", {"tin": device.tin, "bhfId": device.branch_id, **item}, await self._headers(device))

    async def submit_sale(self, device: Device, body: dict) -> Receipt:
        try:
            data = await self._call("/saveTrnsSalesOsdc", body, await self._headers(device))
        except (EtimsTransient, EtimsRejected):
            self._keys.pop(device, None)  # fetch a fresh key next time in case that was the problem
            raise
        got = data.get("data") or {}
        return Receipt(receipt_no=str(got.get("rcptNo") or ""), sdc_id=got.get("sdcId"), sdc_time=got.get("vsdcRcptPbctDate"), signature=got.get("rcptSign"), internal_data=got.get("intrlData"))


_fake = FakeEtims()


def is_live() -> bool:
    return bool(settings.etims_base_url)


def get_etims() -> EtimsClient:
    return OscuClient() if is_live() else _fake


def fake_etims() -> FakeEtims:
    return _fake
