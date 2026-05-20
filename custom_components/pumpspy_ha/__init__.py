"""The Pumpspy-HA integration."""
from __future__ import annotations
from datetime import timedelta
import logging
from homeassistant.helpers import entity_registry
from homeassistant.helpers.storage import Store

from homeassistant.helpers.device_registry import DeviceEntry

from .pypumpspy import (
    InvalidAccessToken,
    PumpSpyAuthError,
    PumpSpyConnectionError,
    PumpSpyDataError,
    Pumpspy,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)


from .const import (
    CONF_DEVICEID,
    CONF_MONTHLY,
    CONF_WEEKLY,
    DOMAIN,
)


PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pumpspy-HA from a config entry."""
    api: Pumpspy = Pumpspy(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        device_id=entry.data[CONF_DEVICEID],
    )

    if not entry.options:
        await async_update_options(hass, entry)

    setup_error: Exception | None = None
    try:
        await api.setup()
    except PumpSpyAuthError as err:
        raise ConfigEntryAuthFailed("PumpSpy authentication failed") from err
    except (PumpSpyConnectionError, PumpSpyDataError) as err:
        setup_error = err
        _LOGGER.warning("PumpSpy setup failed; starting with cached/restored data: %s", err)
        _configure_offline_api_defaults(hass, entry, api)

    coordinator = PumpspyCoordinator(
        hass=hass,
        entry_id=entry.entry_id,
        api=api,
        weekly=entry.options.get(CONF_WEEKLY),
        monthly=entry.options.get(CONF_MONTHLY),
    )
    await coordinator.async_load_cache()

    if setup_error is not None:
        coordinator.mark_api_error(setup_error)
    else:
        await coordinator.async_refresh()
        if not coordinator.last_update_success and not coordinator.data:
            _LOGGER.warning(
                "PumpSpy initial refresh failed; starting with restored entity data"
            )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    # hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


def _configure_offline_api_defaults(
    hass: HomeAssistant, entry: ConfigEntry, api: Pumpspy
) -> None:
    """Fill enough device metadata to restore entities while PumpSpy is offline."""
    device_id = str(entry.data[CONF_DEVICEID])
    api.device_id = entry.data[CONF_DEVICEID]
    api.device_name = _offline_device_name(entry)

    ent_reg = entity_registry.async_get(hass)
    has_backup_entities = any(
        ent.config_entry_id == entry.entry_id and f"{device_id}_backup_" in ent.unique_id
        for ent in ent_reg.entities.values()
        if ent.unique_id
    )
    if has_backup_entities:
        api.iddevice_type = 3


def _offline_device_name(entry: ConfigEntry) -> str:
    """Return a readable device name when PumpSpy metadata is unavailable."""
    title = entry.title or "PumpSpy"
    if title.startswith("Pumpspy (") and title.endswith(")"):
        return title[len("Pumpspy (") : -1]
    return title


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle options update."""

    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_update_options(hass: HomeAssistant, config_entry: ConfigEntry):
    """Configure optional sensors"""
    options = {
        CONF_WEEKLY: config_entry.data.get(CONF_WEEKLY, False),
        CONF_MONTHLY: config_entry.data.get(CONF_MONTHLY, False),
    }
    hass.config_entries.async_update_entry(config_entry, options=options)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    ent_reg = entity_registry.async_get(hass)
    entity_ids_to_be_removed = []
    if config_entry.options.get(CONF_WEEKLY) is False:
        entity_ids_to_be_removed.extend(
            [
                entry.entity_id
                for entry in ent_reg.entities.values()
                if entry.config_entry_id == config_entry.entry_id
                and CONF_WEEKLY in entry.unique_id
            ]
        )

    if config_entry.options.get(CONF_MONTHLY) is False:
        entity_ids_to_be_removed.extend(
            [
                entry.entity_id
                for entry in ent_reg.entities.values()
                if entry.config_entry_id == config_entry.entry_id
                and CONF_MONTHLY in entry.unique_id
            ]
        )

    _LOGGER.debug("Entities to be removed: %s", entity_ids_to_be_removed)

    for entity_id in entity_ids_to_be_removed:
        if ent_reg.async_is_registered(entity_id):
            ent_reg.async_remove(entity_id)

    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True


class PumpspyCoordinator(DataUpdateCoordinator):
    """Pumpspy coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        api: Pumpspy,
        weekly: bool,
        monthly: bool,
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Pumpspy",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=300),
        )
        self.api = api
        self.weekly = weekly
        self.monthly = monthly
        self._store = Store(hass, 1, f"{DOMAIN}_{entry_id}_cache")

        self.api_connected = False
        self.data_stale = True
        self.last_successful_update = None
        self.last_error = "not_initialized"
        self.last_error_detail = None
        self.restored_entity_states = {}

        self.intervals = ["day"]
        if weekly:
            self.intervals.append("week")
        if monthly:
            self.intervals.append("month")

    async def async_load_cache(self) -> None:
        """Load the last successful PumpSpy payload or seeded entity states."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return

        self.last_successful_update = stored.get("last_successful_update")
        self.last_error = stored.get("last_error", "cached")

        data = stored.get("data")
        if isinstance(data, dict) and data.get("current"):
            self.data = data
            self.data_stale = True

        entity_states = stored.get("entity_states")
        if isinstance(entity_states, dict):
            self.restored_entity_states = entity_states

    async def async_save_cache(self, data) -> None:
        """Persist the last successful PumpSpy payload for future outages."""
        await self._store.async_save(
            {
                "data": data,
                "last_successful_update": self.last_successful_update,
                "last_error": self.last_error,
                "entity_states": self.restored_entity_states,
            }
        )

    def mark_api_error(self, err: Exception) -> None:
        """Record a compact API failure reason without discarding cached data."""
        self.api_connected = False
        self.data_stale = True
        self.last_error_detail = str(err)
        if isinstance(err, PumpSpyAuthError):
            self.last_error = "auth_failed"
        elif isinstance(err, PumpSpyConnectionError):
            detail = str(err).lower()
            if "reset" in detail:
                self.last_error = "connection_reset"
            elif "timeout" in detail or "timed out" in detail:
                self.last_error = "timeout"
            else:
                self.last_error = "connection_failed"
        elif isinstance(err, PumpSpyDataError):
            self.last_error = "bad_response"
        else:
            self.last_error = "unknown_error"

    @property
    def diagnostic_attributes(self):
        """Return freshness metadata for PumpSpy entities."""
        return {
            "api_connected": self.api_connected,
            "data_stale": self.data_stale,
            "last_successful_update": self.last_successful_update,
            "data_age_minutes": self.data_age_minutes,
            "last_api_error": self.last_error,
            "last_api_error_detail": self.last_error_detail,
        }

    @property
    def data_age_minutes(self):
        """Return age of the last successful payload in minutes."""
        if not self.last_successful_update:
            return None
        from homeassistant.util import dt

        parsed = dt.parse_datetime(self.last_successful_update)
        if parsed is None:
            return None
        return round((dt.utcnow() - parsed).total_seconds() / 60, 1)

    def restored_state_for(self, unique_id: str):
        """Return a seeded/restored state for an entity unique id."""
        return self.restored_entity_states.get(unique_id)

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            data = await self.api.fetch_data(intervals=self.intervals)
            if not data or not data.get("current"):
                raise PumpSpyDataError("PumpSpy returned no current data")
            from homeassistant.util import dt

            self.api_connected = True
            self.data_stale = False
            self.last_successful_update = dt.utcnow().isoformat()
            self.last_error = "ok"
            self.last_error_detail = None
            await self.async_save_cache(data)
            return data
        except InvalidAccessToken as err:
            _LOGGER.info("Access token expired, will try again")
            self.mark_api_error(err)
            if self.data and self.data.get("current"):
                return self.data
            raise UpdateFailed("PumpSpy access token expired") from err
        except PumpSpyAuthError as err:
            self.mark_api_error(err)
            if self.data and self.data.get("current"):
                return self.data
            raise UpdateFailed("PumpSpy authentication failed") from err
        except (PumpSpyConnectionError, PumpSpyDataError) as err:
            self.mark_api_error(err)
            if self.data and self.data.get("current"):
                return self.data
            raise UpdateFailed(f"PumpSpy update failed: {err}") from err
