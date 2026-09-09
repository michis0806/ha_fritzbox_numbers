"""Verbindungszustand je Rufnummer."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FritzVoipCoordinator
from .const import CONF_KNOWN_NUMBERS
from .entity import FritzVoipNumberEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FritzVoipCoordinator = entry.runtime_data
    nummern = sorted(
        set(entry.data.get(CONF_KNOWN_NUMBERS) or []) | set(coordinator.data or {})
    )
    async_add_entities(FritzVoipVerbunden(coordinator, nr) for nr in nummern)


class FritzVoipVerbunden(FritzVoipNumberEntity, BinarySensorEntity):
    """An, solange die Rufnummer beim Anbieter registriert ist."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = None
    _schluessel = "verbunden"

    @property
    def is_on(self) -> bool | None:
        eintrag = self._eintrag
        return None if eintrag is None else bool(eintrag.get("verbunden"))
