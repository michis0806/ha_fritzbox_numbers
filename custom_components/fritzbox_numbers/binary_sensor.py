"""Verbindungszustand je Rufnummer, Gesprächs- und Update-Status je Mobilteil."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FritzNumbersData, mobilteil_geraet
from .const import CONF_KNOWN_NUMBERS
from .entity import FritzMobilteilEntity, FritzVoipNumberEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    daten: FritzNumbersData = entry.runtime_data
    coordinator = daten.nummern
    nummern = sorted(
        set(entry.data.get(CONF_KNOWN_NUMBERS) or []) | set(coordinator.data or {})
    )
    async_add_entities(FritzVoipVerbunden(coordinator, nr) for nr in nummern)

    dect = daten.mobilteile
    if dect is None:
        return
    gesehen: set[str] = set()

    @callback
    def _neue_mobilteile() -> None:
        """Später angemeldete Mobilteile ohne Neustart aufnehmen."""
        neu = sorted(set(dect.data or {}) - gesehen)
        if not neu:
            return
        gesehen.update(neu)
        for ident in neu:
            mobilteil_geraet(hass, entry, daten, dect.data[ident])
        async_add_entities(
            entity
            for ident in neu
            for entity in (FritzMobilteilImGespraech(dect, ident), FritzMobilteilUpdate(dect, ident))
        )

    _neue_mobilteile()
    entry.async_on_unload(dect.async_add_listener(_neue_mobilteile))


class FritzVoipVerbunden(FritzVoipNumberEntity, BinarySensorEntity):
    """An, solange die Rufnummer beim Anbieter registriert ist."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = None
    _schluessel = "verbunden"

    @property
    def is_on(self) -> bool | None:
        eintrag = self._eintrag
        return None if eintrag is None else bool(eintrag.get("verbunden"))


class FritzMobilteilImGespraech(FritzMobilteilEntity, BinarySensorEntity):
    """An, solange das Mobilteil belegt ist — vom Wählen bzw. Abheben bis zum Auflegen."""

    _attr_translation_key = "in_call"
    _schluessel = "in_call"

    @property
    def is_on(self) -> bool | None:
        eintrag = self._eintrag
        return None if eintrag is None else eintrag["im_gespraech"]


class FritzMobilteilUpdate(FritzMobilteilEntity, BinarySensorEntity):
    """An, wenn die Box ein Firmware-Update für das Mobilteil anbietet."""

    _attr_device_class = BinarySensorDeviceClass.UPDATE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _schluessel = "update"

    @property
    def is_on(self) -> bool | None:
        eintrag = self._eintrag
        return None if eintrag is None else eintrag["update_verfuegbar"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        eintrag = self._eintrag or {}
        return {
            "modell": eintrag.get("modell"),
            "letztes_update": eintrag.get("update_ergebnis"),
            "update_info": eintrag.get("update_info") or None,
        }
