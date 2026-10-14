"""Gemeinsame Basis für die Entities je Rufnummer, Mobilteil und Anrufbeantworter."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FritzDectCoordinator, FritzTelefonieCoordinator, FritzVoipCoordinator
from .const import DOMAIN


class FritzVoipNumberEntity(CoordinatorEntity[FritzVoipCoordinator]):
    """Jede Rufnummer wird ein eigenes Gerät unterhalb der FritzBox."""

    _attr_has_entity_name = True
    _schluessel = ""

    def __init__(self, coordinator: FritzVoipCoordinator, nummer: str) -> None:
        super().__init__(coordinator)
        self._nummer = nummer
        serie = coordinator.geraet["seriennummer"]
        self._attr_unique_id = f"{serie}-{nummer}-{self._schluessel}"
        # Das Geraet selbst legt __init__.py an, hier genuegt die Zuordnung.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{serie}-{nummer}")}
        )

    @property
    def _eintrag(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get(self._nummer)

    @property
    def available(self) -> bool:
        return super().available and self._eintrag is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        eintrag = self._eintrag or {}
        return {
            "nummer": self._nummer,
            "registrar": eintrag.get("registrar"),
            "typ": eintrag.get("typ"),
        }


class FritzMobilteilEntity(CoordinatorEntity[FritzDectCoordinator]):
    """Jedes DECT-Mobilteil wird ein eigenes Gerät unterhalb der FritzBox."""

    _attr_has_entity_name = True
    _schluessel = ""

    def __init__(self, coordinator: FritzDectCoordinator, ident: str) -> None:
        super().__init__(coordinator)
        self._ident = ident
        serie = coordinator.geraet["seriennummer"]
        self._attr_unique_id = f"{serie}-dect-{ident}-{self._schluessel}"
        # Das Geraet legt mobilteil_geraet() an, hier genuegt die Zuordnung.
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{serie}-dect-{ident}")})

    @property
    def _eintrag(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get(self._ident)

    @property
    def available(self) -> bool:
        return super().available and self._eintrag is not None


class FritzAbEntity(CoordinatorEntity[FritzTelefonieCoordinator]):
    """Jeder eingerichtete Anrufbeantworter wird ein eigenes Gerät unterhalb der FritzBox."""

    _attr_has_entity_name = True
    _schluessel = ""

    def __init__(self, coordinator: FritzTelefonieCoordinator, index: str) -> None:
        super().__init__(coordinator)
        self._index = index
        serie = coordinator.geraet["seriennummer"]
        self._attr_unique_id = f"{serie}-tam-{index}-{self._schluessel}"
        # Das Geraet legt __init__.py an, hier genuegt die Zuordnung.
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{serie}-tam-{index}")})

    @property
    def _eintrag(self) -> dict[str, Any] | None:
        return ((self.coordinator.data or {}).get("ab") or {}).get(self._index)

    @property
    def available(self) -> bool:
        return super().available and self._eintrag is not None
