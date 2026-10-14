"""Statustext, verpasste und letzte Anrufe je Rufnummer, Gesamtzahl der verbundenen
Rufnummern und neue Nachrichten je Anrufbeantworter."""
from __future__ import annotations

from typing import Any

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import (
    FritzNumbersData,
    FritzTelefonieCoordinator,
    FritzVoipCoordinator,
    gleiche_nummer,
)
from .const import CONF_KNOWN_NUMBERS, DOMAIN
from .entity import FritzAbEntity, FritzVoipNumberEntity

# Mehr verpasste Anrufe als Attribut aufzulisten bläht nur die Datenbank auf
MAX_VERPASST_ATTRIBUT = 10


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    daten: FritzNumbersData = entry.runtime_data
    coordinator = daten.nummern
    nummern = sorted(
        set(entry.data.get(CONF_KNOWN_NUMBERS) or []) | set(coordinator.data or {})
    )
    entities: list[SensorEntity] = [FritzVoipStatus(coordinator, nr) for nr in nummern]
    entities.append(FritzVoipAnzahl(coordinator))

    tel = daten.telefonie
    if tel is not None:
        if tel.data["anrufe"] is not None:
            entities += [
                entity
                for nr in nummern
                for entity in (FritzVerpassteAnrufe(tel, nr), FritzLetzterAnruf(tel, nr))
            ]
        entities += [FritzAbNeueNachrichten(tel, index) for index in sorted(tel.data["ab"])]
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


def _iso(zeit: datetime | None) -> str | None:
    return zeit.isoformat() if zeit else None


class _FritzAnrufEntity(CoordinatorEntity[FritzTelefonieCoordinator], SensorEntity):
    """Sensoren aus der Anrufliste, je Rufnummer am Gerät der Nummer."""

    _attr_has_entity_name = True
    _schluessel = ""

    def __init__(self, coordinator: FritzTelefonieCoordinator, nummer: str) -> None:
        super().__init__(coordinator)
        self._nummer = nummer
        serie = coordinator.geraet["seriennummer"]
        self._attr_unique_id = f"{serie}-{nummer}-{self._schluessel}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{serie}-{nummer}")})

    @property
    def _anrufe(self) -> list[dict[str, Any]]:
        """Anrufe auf bzw. von dieser Rufnummer, neueste zuerst."""
        return [
            a for a in (self.coordinator.data or {}).get("anrufe") or []
            if gleiche_nummer(a["eigene_nummer"], self._nummer)
        ]


class FritzVerpassteAnrufe(_FritzAnrufEntity):
    """Verpasste Anrufe auf der Rufnummer seit Mitternacht."""

    _attr_translation_key = "missed_calls_today"
    _schluessel = "missed-calls-today"

    @property
    def _heute(self) -> list[dict[str, Any]]:
        heute = dt_util.now().date()
        return [
            a for a in self._anrufe
            if a["typ"] == "verpasst" and a["zeit"] and a["zeit"].date() == heute
        ]

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return len(self._heute)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "anrufe": [
                {"zeit": _iso(a["zeit"]), "nummer": a["nummer"], "name": a["name"]}
                for a in self._heute[:MAX_VERPASST_ATTRIBUT]
            ]
        }


class FritzLetzterAnruf(_FritzAnrufEntity):
    """Zeitpunkt des letzten Anrufs auf bzw. von der Rufnummer, Einzelheiten als Attribute."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_call"
    _schluessel = "last-call"

    @property
    def native_value(self) -> datetime | None:
        anrufe = self._anrufe
        return anrufe[0]["zeit"] if anrufe else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        anrufe = self._anrufe
        if not anrufe:
            return {}
        return {k: anrufe[0][k] for k in ("typ", "nummer", "name", "mobilteil", "dauer_min")}


class FritzAbNeueNachrichten(FritzAbEntity, SensorEntity):
    """Ungehörte Nachrichten auf dem Anrufbeantworter."""

    _attr_translation_key = "new_messages"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _schluessel = "neue-nachrichten"

    @property
    def native_value(self) -> int | None:
        eintrag = self._eintrag
        return None if eintrag is None else eintrag["neu"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        eintrag = self._eintrag or {}
        letzte = eintrag.get("letzte_neue") or {}
        return {
            "gesamt": eintrag.get("nachrichten"),
            "letzte_zeit": _iso(letzte.get("zeit")),
            "letzte_nummer": letzte.get("nummer"),
            "letzte_name": letzte.get("name"),
            "letzte_dauer_min": letzte.get("dauer_min"),
        }
