"""Anrufbeantworter ein- und ausschalten."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FritzNumbersData
from .entity import FritzAbEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    daten: FritzNumbersData = entry.runtime_data
    tel = daten.telefonie
    if tel is None:
        return
    async_add_entities(FritzAbSchalter(tel, index) for index in sorted(tel.data["ab"]))


class FritzAbSchalter(FritzAbEntity, SwitchEntity):
    """An, solange der Anrufbeantworter Anrufe annimmt."""

    _attr_name = None
    _attr_translation_key = "tam"
    _schluessel = "schalter"

    @property
    def is_on(self) -> bool | None:
        eintrag = self._eintrag
        return None if eintrag is None else eintrag["aktiv"]

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.ab_schalten(self._index, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.ab_schalten(self._index, False)
