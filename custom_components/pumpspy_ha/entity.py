"""Base Entity for Pumpspy."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from . import PumpspyCoordinator
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.restore_state import RestoreEntity
from .const import DOMAIN, MANUFACTURER


class PumpspyEntity(CoordinatorEntity[PumpspyCoordinator], RestoreEntity):
    """Defines a base Pumpspy entity."""

    def __init__(self, coordinator: PumpspyCoordinator) -> None:
        """Initialize the entity."""
        self.coordinator = coordinator
        self._restored_native_value = None
        self._restored_attributes = {}
        super().__init__(coordinator)

    async def async_added_to_hass(self) -> None:
        """Restore the last entity state if PumpSpy starts during an API outage."""
        await super().async_added_to_hass()

        seeded = self.coordinator.restored_state_for(self.unique_id)
        if isinstance(seeded, dict) and seeded.get("state") not in (
            None,
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            self._restored_native_value = seeded["state"]
            self._restored_attributes = seeded.get("attributes") or {}
            return

        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._restored_native_value = last_state.state
            self._restored_attributes = dict(last_state.attributes)

    @property
    def available(self) -> bool:
        """Keep last known entity values visible during PumpSpy API outages."""
        return self.has_live_data or self._restored_native_value is not None

    @property
    def has_live_data(self) -> bool:
        """Return true when the coordinator has a usable PumpSpy payload."""
        try:
            return bool(self.coordinator.data["current"][0])
        except (KeyError, IndexError, TypeError):
            return False

    @property
    def current_data(self):
        """Return the current PumpSpy device payload."""
        return self.coordinator.data["current"][0]

    def restored_value(self):
        """Return the restored native value for this entity."""
        return self._restored_native_value

    def attributes_with_diagnostics(self, attributes=None):
        """Merge entity attributes with PumpSpy freshness diagnostics."""
        merged = {}
        if self.coordinator.data_stale and self._restored_attributes:
            merged.update(self._restored_attributes)
        if attributes:
            merged.update(attributes)
        merged.update(self.coordinator.diagnostic_attributes)
        return merged

    @property
    def device_info(self) -> DeviceInfo | None:
        try:
            return DeviceInfo(
                identifiers={(DOMAIN, self.coordinator.data["current"][0]["deviceid"])},
                name=self.coordinator.data["current"][0]["user_nickname"],
                manufacturer=MANUFACTURER,
                model=self.coordinator.data["current"][0]["device_types_name"],
                hw_version=self.coordinator.data["current"][0]["hardware_rev"],
                sw_version=self.coordinator.data["current"][0]["firmware_rev"],
            )
        except (KeyError, IndexError, TypeError):
            device_info = self.coordinator.api.get_device_info()
            device_id = device_info.get("deviceid")
            if device_id is None:
                return None
            return DeviceInfo(
                identifiers={(DOMAIN, device_id)},
                name=device_info.get("device_name") or "PumpSpy",
                manufacturer=MANUFACTURER,
            )
