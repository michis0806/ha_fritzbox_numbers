"""Statustext je Rufnummer und Gesamtzahl der verbundenen Rufnummern."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FritzVoipCoordinator
from .const import CONF_KNOWN_NUMBERS, DOMAIN
from .entity import FritzVoipNumberEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FritzVoipCoordinator = entry.runtime_data
    nummern = sorted(
        set(entry.data.get(CONF_KNOWN_NUMBERS) or []) | set(coordinator.data or {})
    )
    entities: list[SensorEntity] = [FritzVoipStatus(coordinator, nr) for nr in nummern]
    entities.append(FritzVoipAnzahl(coordinator))
    async_add_entities(entities)


class FritzVoipStatus(FritzVoipNumberEntity, SensorEntity):
    """Der unveränderte Statustext der Box, z. B. "registered"."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "registration_status"
    _schluessel = "status"

    @property
    def native_value(self) -> str | None:
        eintrag = self._eintrag
        return None if eintrag is None else eintrag.get("status")


class FritzVoipAnzahl(CoordinatorEntity[FritzVoipCoordinator], SensorEntity):
    """Wie viele Rufnummern gerade registriert sind."""

    _attr_has_entity_name = True
    _attr_translation_key = "registered_numbers"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FritzVoipCoordinator) -> None:
        super().__init__(coordinator)
        serie = coordinator.geraet["seriennummer"]
        self._attr_unique_id = f"{serie}-registered-numbers"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, serie)})

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return sum(1 for e in self.coordinator.data.values() if e.get("verbunden"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daten = self.coordinator.data or {}
        return {
            "gesamt": len(daten),
            "nicht_verbunden": [n for n, e in daten.items() if not e.get("verbunden")],
        }
