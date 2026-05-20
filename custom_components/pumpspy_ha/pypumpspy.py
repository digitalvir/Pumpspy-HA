"""Python package to talk to Pumpspy API."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

AUTH_USERNAME = "IOS"
AUTH_PASSWORD = "secret"

# LIST OF ENDPOINTS
BASE_URL = "http://www.pumpspy.com:8082"
TOKEN_URL = "/oauth/token"
UID_URL = "/users/email/"
LOCATIONS_URL = "/locations/uid/"
DEVICES_URL = "/devices/lid/"
DEVICEINFO_URL = "devices/deviceid"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20, connect=8, sock_connect=8, sock_read=12)
MAX_ATTEMPTS = 2
RETRY_SLEEP_SECONDS = 1

LOG = logging.getLogger(__name__)

device_types = {
    2: {
        "endpoint": "pump_outlets",
        "interval_endpoint": "pump_outlet",
        "has_backup": False,
    },
    3: {"endpoint": "bbs", "interval_endpoint": "bbs", "has_backup": True},
    4: {
        "endpoint": "rht_outlets",
        "interval_endpoint": "rht_outlet",
        "has_backup": False,
    },
    5: {
        "endpoint": "rht_outlets",
        "interval_endpoint": "rht_outlet",
        "has_backup": False,
    },
    6: {
        "endpoint": "rht_outlets",
        "interval_endpoint": "rht_outlet",
        "has_backup": False,
    },
}


class PumpSpyError(Exception):
    """Base PumpSpy client error."""


class PumpSpyAuthError(PumpSpyError):
    """Authentication failed."""


class PumpSpyConnectionError(PumpSpyError):
    """PumpSpy API connection failed."""


class PumpSpyDataError(PumpSpyError):
    """PumpSpy API returned unusable data."""


class InvalidAccessToken(PumpSpyAuthError):
    """PumpSpy access token expired or was rejected."""


class Pumpspy:
    """Python class to talk to Pumpspy API."""

    def __init__(self, username, password, device_id=None, iddevice_type=None) -> None:
        """Initialize."""
        self.username = username
        self.password = password
        self.device_name = None
        self.device_id = device_id
        self.iddevice_type = iddevice_type
        self.access_token = None
        self.uid = None
        self.lid = None

    async def setup(self) -> None:
        """Set up the class with access token and user id."""
        await self.get_token()
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            await self.get_uid(session=session)
            if self.device_id is not None:
                device_info = await self.get_device_info_from_id(session=session)
                if not device_info:
                    raise PumpSpyDataError(
                        f"No device info returned for PumpSpy device {self.device_id}"
                    )
                self.iddevice_type = device_info[0]["iddevice_types"]
                self.device_name = device_info[0]["device_types_name"]

    async def _request_json(
        self,
        session: aiohttp.ClientSession,
        method: str,
        url: str,
        *,
        auth: aiohttp.BasicAuth | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Request JSON from PumpSpy with bounded retries and useful errors."""
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with session.request(
                    method,
                    url,
                    auth=auth,
                    data=data,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    text = await resp.text()
                    try:
                        payload = json.loads(text) if text else None
                    except json.JSONDecodeError as err:
                        raise PumpSpyDataError(
                            f"PumpSpy returned non-JSON response from {url}: HTTP {resp.status}"
                        ) from err

                    if resp.status == 200:
                        return payload

                    if url.endswith(TOKEN_URL) and resp.status in (400, 401):
                        raise PumpSpyAuthError("PumpSpy rejected username or password")

                    if (
                        resp.status == 401
                        and isinstance(payload, dict)
                        and payload.get("error") == "invalid_token"
                    ):
                        raise InvalidAccessToken("PumpSpy access token expired")

                    raise PumpSpyDataError(
                        f"PumpSpy returned HTTP {resp.status} from {url}: {text[:200]}"
                    )
            except InvalidAccessToken:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_error = err
                if attempt >= MAX_ATTEMPTS:
                    break
                LOG.debug(
                    "PumpSpy request failed on attempt %s/%s: %s",
                    attempt,
                    MAX_ATTEMPTS,
                    err,
                )
                await asyncio.sleep(RETRY_SLEEP_SECONDS)

        raise PumpSpyConnectionError(f"PumpSpy request failed for {url}: {last_error}")

    async def get_token(self) -> None:
        """Get bearer token."""
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
        }

        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            response = await self._request_json(
                session,
                "POST",
                f"{BASE_URL}{TOKEN_URL}",
                auth=aiohttp.BasicAuth(AUTH_USERNAME, AUTH_PASSWORD),
                headers=headers,
                data=data,
            )
            if not isinstance(response, dict) or not response.get("access_token"):
                raise PumpSpyAuthError("PumpSpy authorization response had no access token")
            self.access_token = response["access_token"]
            LOG.debug("Got PumpSpy access token")

    async def get_uid(self, session: aiohttp.ClientSession) -> None:
        """Get the uid of the user."""
        response = await self._request_json(
            session,
            "GET",
            f"{BASE_URL}{UID_URL}{self.username}",
            headers=self.authed_headers(),
        )
        if not response:
            raise PumpSpyDataError("PumpSpy returned no user id records")
        self.uid = response[0]["uid"]
        LOG.debug("Got PumpSpy uid")

    async def get_locations(self):
        """Get the available locations."""
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            return await self._request_json(
                session,
                "GET",
                f"{BASE_URL}{LOCATIONS_URL}{self.uid}",
                headers=self.authed_headers(),
            )

    async def get_devices(self):
        """Get the available devices."""
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            return await self._request_json(
                session,
                "GET",
                f"{BASE_URL}{DEVICES_URL}{self.lid}",
                headers=self.authed_headers(),
            )

    async def get_device_info_from_id(self, session: aiohttp.ClientSession):
        """Get the device info."""
        return await self._request_json(
            session,
            "GET",
            f"{BASE_URL}/{DEVICEINFO_URL}/{self.device_id}",
            headers=self.authed_headers(),
        )

    def set_location(self, lid):
        """Setter for location id."""
        self.lid = lid

    def get_device_info(self):
        """Getter for device id."""
        return {"deviceid": self.device_id, "device_name": self.device_name}

    def has_backup(self):
        """Check if the device has a backup pump."""
        if self.iddevice_type is None:
            return False
        return device_types.get(self.iddevice_type, {}).get("has_backup", False)

    def device_type(self) -> dict[str, Any]:
        """Return the PumpSpy endpoint mapping for this device type."""
        if self.iddevice_type is None:
            raise PumpSpyDataError("PumpSpy device type is not set")
        device_type = device_types.get(self.iddevice_type)
        if device_type is None:
            raise PumpSpyDataError(
                f"PumpSpy returned unknown device type {self.iddevice_type}"
            )
        return device_type

    async def fetch_data(self, intervals):
        """Get all the data from the API."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                try:
                    data = {"current": None, "ac": {}, "dc": {}}
                    data["current"] = await self.fetch_current_data(session=session)
                    if not data["current"]:
                        raise PumpSpyDataError("PumpSpy returned no current data")

                    for interval in intervals:
                        data["ac"][interval] = await self.fetch_interval_data(
                            session=session, motor="ac", interval=interval
                        )
                        if self.has_backup() is True:
                            data["dc"][interval] = await self.fetch_interval_data(
                                session=session, motor="dc", interval=interval
                            )
                    LOG.debug(data)
                    return data
                except InvalidAccessToken:
                    if attempt >= MAX_ATTEMPTS:
                        raise
                    LOG.info("PumpSpy access token expired; refreshing")
                    await self.get_token()
                    await asyncio.sleep(RETRY_SLEEP_SECONDS)

        raise PumpSpyConnectionError("PumpSpy data fetch failed after token refresh")

    async def fetch_current_data(self, session: aiohttp.ClientSession):
        """Get the current data."""
        endpoint = self.device_type()["endpoint"]
        updated_url = f"{BASE_URL}/{endpoint}/deviceid/{self.device_id}"
        LOG.debug("Querying PumpSpy API: %s", updated_url)
        return await self._request_json(
            session,
            "GET",
            updated_url,
            headers=self.authed_headers(),
        )

    async def fetch_interval_data(
        self, session: aiohttp.ClientSession, motor: str, interval: str
    ):
        """
        Get the interval data.
        motor = "ac" for main, "dc" for backup
        interval = "day", "month", "week"
        """
        endpoint = self.device_type()["interval_endpoint"]
        updated_url = f"{BASE_URL}/{endpoint}_cycles/deviceid/{self.device_id}"
        if self.has_backup() is True:
            updated_url = f"{updated_url}/motor/{motor}"
        updated_url = f"{updated_url}/interval/{interval}"
        LOG.debug("Querying PumpSpy API: %s", updated_url)
        return await self._request_json(
            session,
            "GET",
            updated_url,
            headers=self.authed_headers(),
        )

    def authed_headers(self):
        """Return headers with bearer token."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
