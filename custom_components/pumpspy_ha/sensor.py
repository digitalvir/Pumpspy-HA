"""Platform for sensor integration."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from collections.abc import Mapping
import pytz

from homeassistant.helpers.typing import StateType
from .entity import PumpspyEntity

# from .pumpspy_ha import PumpspyEntity, pumpspy
from homeassistant.const import (
    PERCENTAGE,
    UnitOfVolume,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt
from .const import (
    CONF_BACKUP_PUMP,
    CONF_CYCLES,
    CONF_DAILY,
    CONF_DEVICE_NAME,
    CONF_DEVICEID,
    CONF_GALLONS,
    CONF_MAIN_PUMP,
    CONF_MONTHLY,
    CONF_WEEKLY,
    DOMAIN,
)

interval_names = {"day": CONF_DAILY, "week": CONF_WEEKLY, "month": CONF_MONTHLY}


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    new_devices = [
        SignalStrengthSensor(coordinator=coordinator),
        LastCycleSensor(coordinator=coordinator, pump=CONF_MAIN_PUMP),
        LastSuccessfulUpdateSensor(coordinator=coordinator),
        DataAgeMinutesSensor(coordinator=coordinator),
        LastErrorSensor(coordinator=coordinator),
    ]

    for interval in coordinator.intervals:
        new_devices.append(
            TotalingSensor(
                coordinator=coordinator,
                pump=CONF_MAIN_PUMP,
                sensor_type=CONF_CYCLES,
                interval=interval_names[interval],
            )
        )
        new_devices.append(
            TotalingSensor(
                coordinator=coordinator,
                pump=CONF_MAIN_PUMP,
                sensor_type=CONF_GALLONS,
                interval=interval_names[interval],
            )
        )

        # add the backup pump sensors if the device has it
        if coordinator.api.has_backup() is True:
            new_devices.append(
                TotalingSensor(
                    coordinator=coordinator,
                    pump=CONF_BACKUP_PUMP,
                    sensor_type=CONF_CYCLES,
                    interval=interval_names[interval],
                )
            )
            new_devices.append(
                TotalingSensor(
                    coordinator=coordinator,
                    pump=CONF_BACKUP_PUMP,
                    sensor_type=CONF_GALLONS,
                    interval=interval_names[interval],
                )
            )

    # add backup pump related items if applicable
    if coordinator.api.has_backup() is True:
        new_devices.append(
            LastCycleSensor(coordinator=coordinator, pump=CONF_BACKUP_PUMP)
        )
        new_devices.append(BatterySensor(coordinator=coordinator))

    if new_devices:
        async_add_entities(new_devices)


class SignalStrengthSensor(PumpspyEntity, SensorEntity):
    """Signal Strength Sensor"""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        self._available = True
        self._attr_native_unit_of_measurement = "dBm"
        self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH

        device_info = self.coordinator.api.get_device_info()

        self._attr_unique_id = f"{device_info[CONF_DEVICEID]}_rssi"
        self._attr_name = f"{device_info[CONF_DEVICE_NAME]} RSSI"

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Get value"""
        if not self.has_live_data:
            return self.restored_value()
        return self.current_data["last_rssi"]

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if not self.has_live_data:
            return self.attributes_with_diagnostics()
        return self.attributes_with_diagnostics(
            {
                "last_rssi_time": dt.as_utc(
                    datetime.fromtimestamp(
                        self.current_data["last_rssi_time"] / 1000,
                        pytz.UTC,
                    )
                )
            }
        )


class LastSuccessfulUpdateSensor(PumpspyEntity, SensorEntity):
    """Last successful PumpSpy update sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        device_info = self.coordinator.api.get_device_info()
        self._attr_unique_id = f"{device_info[CONF_DEVICEID]}_pumpspy_last_successful_update"
        self._attr_name = f"{device_info[CONF_DEVICE_NAME]} PumpSpy Last Successful Update"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return self.coordinator.last_successful_update is not None

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        if not self.coordinator.last_successful_update:
            return None
        return dt.parse_datetime(self.coordinator.last_successful_update)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self.attributes_with_diagnostics()


class DataAgeMinutesSensor(PumpspyEntity, SensorEntity):
    """Age of the last successful PumpSpy payload."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        device_info = self.coordinator.api.get_device_info()
        self._attr_unique_id = f"{device_info[CONF_DEVICEID]}_pumpspy_data_age_minutes"
        self._attr_name = f"{device_info[CONF_DEVICE_NAME]} PumpSpy Data Age"
        self._attr_native_unit_of_measurement = "min"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return self.coordinator.data_age_minutes is not None

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        return self.coordinator.data_age_minutes

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self.attributes_with_diagnostics()


class LastErrorSensor(PumpspyEntity, SensorEntity):
    """Last PumpSpy API error sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        device_info = self.coordinator.api.get_device_info()
        self._attr_unique_id = f"{device_info[CONF_DEVICEID]}_pumpspy_last_error"
        self._attr_name = f"{device_info[CONF_DEVICE_NAME]} PumpSpy Last Error"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        return self.coordinator.last_error

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self.attributes_with_diagnostics(
            {"detail": self.coordinator.last_error_detail}
        )


class BatterySensor(PumpspyEntity, SensorEntity):
    """Battery Sensor"""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        self._available = True
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.BATTERY

        device_info = self.coordinator.api.get_device_info()

        self._attr_unique_id = f"{device_info[CONF_DEVICEID]}_battery"
        self._attr_name = f"{device_info[CONF_DEVICE_NAME]} Battery"

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Native value"""
        if not self.has_live_data:
            return self.restored_value()
        return self.current_data["battery_charge_percentage"]

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Attributes"""
        if not self.has_live_data:
            return self.attributes_with_diagnostics()
        return self.attributes_with_diagnostics(
            {
                "voltage": self.current_data["battery_voltage"] / 1000,
                "estimated_life": round(
                    self.current_data["battery_estimated_life"], 1
                ),
                "tested_time": dt.as_utc(
                    datetime.fromtimestamp(
                        self.current_data["battery_tested_time"] / 1000,
                        pytz.UTC,
                    )
                ),
                "updated": dt.as_utc(
                    datetime.fromtimestamp(
                        self.current_data["battery_updated"] / 1000,
                        pytz.UTC,
                    )
                ),
            }
        )


class TotalingSensor(PumpspyEntity, SensorEntity):
    """Totaling Sensor"""

    def __init__(self, coordinator, pump: str, sensor_type: str, interval: str):
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        self._available = True
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._pump = pump
        self._type = sensor_type
        self._interval = interval
        self._motor = "ac" if pump == CONF_MAIN_PUMP else "dc"

        self._interval_converted = None
        if interval == CONF_DAILY:
            self._interval_converted = "day"
        elif interval == CONF_WEEKLY:
            self._interval_converted = "week"
        elif interval == CONF_MONTHLY:
            self._interval_converted = "month"

        device_info = self.coordinator.api.get_device_info()
        if sensor_type == "gallons":
            self._attr_native_unit_of_measurement = UnitOfVolume.GALLONS

        self._attr_unique_id = (
            f"{device_info[CONF_DEVICEID]}_{pump}_{interval}_{sensor_type}"
        )
        self._attr_name = (
            f"{device_info[CONF_DEVICE_NAME]} {pump} {interval} {sensor_type}".title()
        )

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        if not self.has_live_data:
            return self.restored_value()
        try:
            data = self.coordinator.data[self._motor][self._interval_converted][0]
            data_type = "total_count" if self._type == CONF_CYCLES else self._type
            if data["year_num"] != datetime.now().year:
                return 0
            elif (
                self._interval == CONF_WEEKLY
                and data["week_num"] == datetime.now().isocalendar().week
            ):
                return data[data_type]
            elif data["month_num"] == datetime.now().month:
                if (
                    self._interval == CONF_DAILY
                    and data["day_num"] == datetime.now().day
                ):
                    return data[data_type]
                elif self._interval == CONF_MONTHLY:
                    return data[data_type]
                else:
                    return 0
            else:
                return 0
        except Exception:  # pylint: disable=broad-except
            return 0

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self.attributes_with_diagnostics()


class LastCycleSensor(PumpspyEntity, SensorEntity):
    """Daily Gallon Sensor"""

    def __init__(self, coordinator, pump: str):
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)
        self._available = True
        self._pump = pump
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._pre_key = "" if self._pump == CONF_MAIN_PUMP else "backup_"

        device_info = self.coordinator.api.get_device_info()

        self._attr_unique_id = f"{device_info[CONF_DEVICEID]}_{pump}_last_cycle"
        self._attr_name = f"{device_info[CONF_DEVICE_NAME]} {pump.title()} Last Cycle"

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        if not self.has_live_data:
            restored = self.restored_value()
            if not restored:
                return None
            return dt.parse_datetime(restored) or restored
        return dt.as_utc(
            datetime.fromtimestamp(
                self.current_data[f"{self._pre_key}lastcycletime"] / 1000,
                pytz.UTC,
            )
        )

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if not self.has_live_data:
            return self.attributes_with_diagnostics()
        return self.attributes_with_diagnostics(
            {
                "duration": round(
                    self.current_data[f"{self._pre_key}cycleduration"] / 1000,
                    1,
                )
            }
        )
