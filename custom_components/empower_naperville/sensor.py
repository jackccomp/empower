"""Snapshot sensors. Historical energy is imported separately into Recorder."""
from datetime import datetime
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, NAME

DESCRIPTIONS = (
    SensorEntityDescription(key="latest_kwh", name="Latest interval energy", device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR),
    SensorEntityDescription(key="total_kwh", name="Available history energy", device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR),
    SensorEntityDescription(key="count", name="Reading count", entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key="first", name="First reading", device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key="latest", name="Latest reading", device_class=SensorDeviceClass.TIMESTAMP),
    SensorEntityDescription(key="received", name="Last upload", device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN]["state"]["coordinator"]
    async_add_entities(EmpowerSensor(coordinator, entry, description) for description in DESCRIPTIONS)


class EmpowerSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=NAME, manufacturer="Empower Naperville", model="Home Assistant browser app")

    @property
    def available(self):
        return self.coordinator.data is not None and super().available

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        value = self.coordinator.data[self.entity_description.key]
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
            return datetime.fromisoformat(value)
        return value
