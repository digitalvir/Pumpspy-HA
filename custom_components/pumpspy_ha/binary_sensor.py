"""Platform for binary sensor integration."""
from __future__ import annotations
from typing import Any
from collections.abc import Mapping

from homeassistant.const import STATE_ON
from homeassistant.helpers.entity import EntityCategory

from .entity import PumpspyEntity
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from .const import (
    ALERT_AC_POWER_LOSS,
    ALERT_BACKUP_EXCESSIVE_CURRET,
    ALERT_BACKUP_EXCESSIVE_RUN_TIME,
    ALERT_BACKUP_PUMP_FAILURE,
    ALERT_BATTERY_CHARGE_LEVEL,
    ALERT_CONNECTED,
    ALERT_EXCESSIVE_CURRENT,
    ALERT_EXCESSIVE_RUN_TIME,
    ALERT_HIGH_WATER,
    ALERT_PRIMARY_PUMP_FAILURE,
    CONF_DEVICE_NAME,
    CONF_DEVICEID,
    DOMAIN,
)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    new_devices = [
        PumpSpyApiConnectedBinarySensor(coordinator=coordinator),
        PumpSpyDataStaleBinarySensor(coordinator=coordinator),
        AlertBinarySensor(coordinator=coordinator, alert=ALERT_CONNECTED),
        AlertBinarySensor(coordinator=coordinator, alert=ALERT_HIGH_WATER),
        AlertBinarySensor(coordinator=coordinator, alert=ALERT_AC_POWER_LOSS),
        AlertBinarySensor(coordinator=coordinator, alert=ALERT_EXCESSIVE_CURRENT),
        AlertBinarySensor(coordinator=coordinator, alert=ALERT_EXCESSIVE_RUN_TIME),
    ]

    if coordinator.api.has_backup() is True:
        new_devices.extend(
            [
                AlertBinarySensor(
                    coordinator=coordinator, alert=ALERT_PRIMARY_PUMP_FAILURE
                ),
                AlertBinarySensor(
                    coordinator=coordinator, alert=ALERT_BATTERY_CHARGE_LEVEL
                ),
                AlertBinarySensor(
                    coordinator=coordinator, alert=ALERT_BACKUP_EXCESSIVE_CURRET
                ),
                AlertBinarySensor(
                    coordinator=coordinator, alert=ALERT_BACKUP_EXCESSIVE_RUN_TIME
                ),
                AlertBinarySensor(
                    coordinator=coordinator, alert=ALERT_BACKUP_PUMP_FAILURE
                ),
            ]
        )
    if new_devices:
        async_add_entities(new_devices)


class PumpSpyApiConnectedBinarySensor(PumpspyEntity, BinarySensorEntity):
    """PumpSpy API connectivity sensor."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        device_info = self.coordinator.api.get_device_info()
        self._attr_unique_id = f"{device_info[CONF_DEVICEID]}_pumpspy_api_connected"
        self._attr_name = f"{device_info[CONF_DEVICE_NAME]} PumpSpy API Connected"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.api_connected

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self.attributes_with_diagnostics()


class PumpSpyDataStaleBinarySensor(PumpspyEntity, BinarySensorEntity):
    """PumpSpy data stale sensor."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        device_info = self.coordinator.api.get_device_info()
        self._attr_unique_id = f"{device_info[CONF_DEVICEID]}_pumpspy_data_stale"
        self._attr_name = f"{device_info[CONF_DEVICE_NAME]} PumpSpy Data Stale"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data_stale

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self.attributes_with_diagnostics()


class AlertBinarySensor(PumpspyEntity, BinarySensorEntity):
    """Alert Binary Sensor"""

    def __init__(self, coordinator, alert: str):
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        self._available = True
        self._alert = alert
        self._attr_device_class = (
            BinarySensorDeviceClass.CONNECTIVITY
            if alert == ALERT_CONNECTED
            else BinarySensorDeviceClass.PROBLEM
        )
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        device_info = self.coordinator.api.get_device_info()

        self._attr_unique_id = f"{device_info[CONF_DEVICEID]}_{alert}"
        self._attr_name = (
            f'{device_info[CONF_DEVICE_NAME]} {alert.replace("_", " ").title()}'
        )

    @property
    def is_on(self) -> bool | None:
        if not self.has_live_data:
            restored = self.restored_value()
            if restored is None:
                return None
            return restored == STATE_ON
        val = self.current_data[self._alert]["state"]
        if self._alert == ALERT_BATTERY_CHARGE_LEVEL:
            val = not bool(val)
        return val

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if not self.has_live_data:
            return self.attributes_with_diagnostics()
        return self.attributes_with_diagnostics(
            {"message": self.current_data[self._alert]["message"]}
        )
