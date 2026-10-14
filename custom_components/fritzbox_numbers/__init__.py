"""FritzBox Rufnummern — Registrierungsstatus der VoIP-Nummern über TR-064.

Die offizielle fritz-Integration (FRITZ!Box Tools) liefert Verbindungsstatus,
Bandbreite und Anwesenheitserkennung, aber nicht den Registrierungszustand der
Rufnummern. Diese Integration fragt dafür den Dienst X_VoIP:1 ab, dazu die
DECT-Mobilteile über X_AVM-DE_Dect:1.

Voraussetzung in der FritzBox: Heimnetz > Netzwerk > Netzwerkeinstellungen >
"Zugriff für Anwendungen zulassen". UPnP wird nicht gebraucht.

TR-064 verlangt HTTP-Digest-Auth, das kann aiohttp nicht. Die Aufrufe laufen
deshalb mit urllib im Executor statt asynchron — bei einem Poll alle fünf
Minuten ist das unkritisch und spart eine zusätzliche Abhängigkeit.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from xml.sax.saxutils import escape, unescape

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_KNOWN_NUMBERS,
    CONTROL_PATH,
    DECT_CONTROL_PATH,
    DECT_GRACE_SECONDS,
    DECT_SERVICE,
    DECT_UPDATE_INTERVAL,
    DESC_PATH,
    DOMAIN,
    GRACE_SECONDS,
    REQUEST_TIMEOUT,
    SERVICE,
    STATUS_REGISTERED,
    TR064_PORT,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor"]

VOIP = (SERVICE, CONTROL_PATH)
DECT = (DECT_SERVICE, DECT_CONTROL_PATH)


class FritzVoipError(Exception):
    """Box nicht erreichbar oder TR-064 nicht aktiv."""


class FritzVoipAuthError(FritzVoipError):
    """Zugangsdaten falsch oder Berechtigung fehlt."""


def _feld(xml: str, name: str) -> str | None:
    treffer = re.search(rf"<{name}>(.*?)</{name}>", xml, re.S)
    return unescape(treffer.group(1)) if treffer else None


def _bloecke(xml: str, tag: str) -> list[dict[str, str]]:
    """Alle <tag>…</tag>-Abschnitte als Dict ihrer Felder."""
    return [
        dict(re.findall(r"<([\w\-]+)>(.*?)</\1>", block, re.S))
        for block in re.findall(rf"<{tag}>(.*?)</{tag}>", unescape(xml), re.S)
    ]


def soap(
    host: str,
    user: str,
    pw: str,
    aktion: str,
    args: dict[str, Any] | None = None,
    dienst: tuple[str, str] = VOIP,
) -> str:
    """Einen TR-064-Aufruf ausführen. Blockierend — nur im Executor aufrufen."""
    service, pfad = dienst
    argx = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in (args or {}).items())
    rumpf = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
        ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{aktion} xmlns:u="{service}">{argx}</u:{aktion}>'
        "</s:Body></s:Envelope>"
    ).encode()

    basis = f"http://{host}:{TR064_PORT}"
    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password(None, basis, user, pw)
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(mgr))
    req = urllib.request.Request(
        f"{basis}{pfad}",
        data=rumpf,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SoapAction": f"{service}#{aktion}",
        },
    )
    try:
        with opener.open(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        text = err.read().decode("utf-8", "replace")
        code = _feld(text, "errorCode") or ""
        # AVM verpackt auch Anmeldefehler in einen SOAP-Fault mit HTTP 500
        if err.code == 401 or code in ("401", "606"):
            grund = {
                "606": "Benutzer hat keine Berechtigung 'FRITZ!Box Einstellungen'",
            }.get(code, "Benutzername oder Passwort falsch")
            raise FritzVoipAuthError(grund) from err
        beschreibung = _feld(text, "errorDescription") or err.reason
        raise FritzVoipError(f"HTTP {err.code}: {beschreibung}") from err
    except OSError as err:
        raise FritzVoipError(f"{host} nicht erreichbar: {err}") from err


def geraetedaten(host: str) -> dict[str, Any]:
    """Modell und Seriennummer aus tr64desc.xml — ohne Anmeldung lesbar.

    Ein 404 hier ist das typische Zeichen für abgeschaltetes TR-064: der Port
    antwortet, die Beschreibungsdatei fehlt aber.
    """
    try:
        with urllib.request.urlopen(
            f"http://{host}:{TR064_PORT}{DESC_PATH}", timeout=REQUEST_TIMEOUT
        ) as resp:
            xml = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise FritzVoipError(
                "TR-064 ist nicht aktiv — in der FritzBox unter Heimnetz > Netzwerk > "
                "Netzwerkeinstellungen 'Zugriff für Anwendungen zulassen' einschalten"
            ) from err
        raise FritzVoipError(f"HTTP {err.code} beim Lesen von {DESC_PATH}") from err
    except OSError as err:
        raise FritzVoipError(f"{host} nicht erreichbar: {err}") from err

    return {
        "name": _feld(xml, "friendlyName") or "FRITZ!Box",
        "modell": _feld(xml, "modelName") or "FRITZ!Box",
        "hersteller": _feld(xml, "manufacturer") or "AVM",
        "seriennummer": _feld(xml, "serialNumber") or host,
        # Boxen ohne DECT-Basis bieten den Dienst gar nicht erst an
        "dect": DECT_SERVICE in xml,
    }


def rufnummern(host: str, user: str, pw: str) -> dict[str, dict[str, Any]]:
    """Belegte VoIP-Konten mit ihrem Registrierungszustand."""
    konten_xml = soap(host, user, pw, "X_AVM-DE_GetVoIPAccounts")
    nummern_xml = soap(host, user, pw, "X_AVM-DE_GetNumbers")
    # Leere Account-Slots liefert die Box mit leerer VoIPNumber mit
    konten = [k for k in _bloecke(konten_xml, "Account") if k.get("VoIPNumber")]
    benannt = {n.get("Number"): n for n in _bloecke(nummern_xml, "Item")}

    ergebnis: dict[str, dict[str, Any]] = {}
    for konto in konten:
        idx = konto.get("VoIPAccountIndex", "0")
        nummer = konto["VoIPNumber"]
        status = _feld(
            soap(host, user, pw, "X_AVM-DE_GetVoIPStatus", {"NewVoIPAccountIndex": idx}),
            "NewX_AVM-DE_VoIPStatus",
        ) or "unbekannt"
        ergebnis[nummer] = {
            "nummer": nummer,
            "name": (benannt.get(nummer, {}).get("Name") or "").strip(),
            "typ": benannt.get(nummer, {}).get("Type", ""),
            "registrar": konto.get("VoIPRegistrar", ""),
            "index": int(idx) if idx.isdigit() else idx,
            "status": status,
            "verbunden": status == STATUS_REGISTERED,
        }
    return ergebnis


def mobilteile(host: str, user: str, pw: str) -> dict[str, dict[str, Any]]:
    """Angemeldete DECT-Mobilteile.

    GetDectListPath liefert den Pfad zu einer XML-Liste aller Mobilteile — zwei
    Abrufe statt einem GetGenericDectEntry je Mobilteil. Die Session-ID im Pfad
    vergibt die Box je Benutzer nur einmal, der kurze Takt häuft also keine
    Sessions an. Der Pfad enthält die Session-ID und gehört nicht ins Log.
    """
    pfad = _feld(soap(host, user, pw, "GetDectListPath", dienst=DECT), "NewDectListPath")
    if not pfad:
        raise FritzVoipError("Box liefert keinen Pfad zur DECT-Liste")
    try:
        with urllib.request.urlopen(
            f"http://{host}:{TR064_PORT}{pfad}", timeout=REQUEST_TIMEOUT
        ) as resp:
            xml = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        raise FritzVoipError(f"HTTP {err.code} beim Lesen der DECT-Liste") from err
    except OSError as err:
        raise FritzVoipError(f"{host} nicht erreichbar: {err}") from err

    ergebnis: dict[str, dict[str, Any]] = {}
    for item in _bloecke(xml, "Item"):
        if not (ident := item.get("Id")):
            continue
        ergebnis[ident] = {
            "id": ident,
            "name": (item.get("Name") or "").strip(),
            "modell": item.get("Model", ""),
            # Active ist 1 vom Wählen bis zum Auflegen, je Mobilteil getrennt
            "im_gespraech": item.get("Active") == "1",
            "update_verfuegbar": item.get("UpdateAvailable") == "1",
            "update_ergebnis": item.get("UpdateSuccessful", ""),
            "update_info": item.get("UpdateInfo", ""),
        }
    return ergebnis


@dataclass
class FritzNumbersData:
    """Was eine eingerichtete Box zur Laufzeit an ihre Plattformen weitergibt."""

    nummern: FritzVoipCoordinator
    mobilteile: FritzDectCoordinator | None
    geraet: dict[str, Any]
    hub_id: str


def mobilteil_geraet(
    hass: HomeAssistant, entry: ConfigEntry, daten: FritzNumbersData, eintrag: dict[str, Any]
) -> None:
    """Das Gerät eines Mobilteils unterhalb der Box anlegen oder auffrischen."""
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{daten.geraet['seriennummer']}-dect-{eintrag['id']}")},
        name=eintrag.get("name") or f"Mobilteil {eintrag['id']}",
        manufacturer=daten.geraet["hersteller"],
        model=eintrag.get("modell") or "DECT",
        via_device_id=daten.hub_id,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    try:
        info = await hass.async_add_executor_job(geraetedaten, host)
    except FritzVoipError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = FritzVoipCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    # Einmal gesehene Rufnummern merken, damit ihre Entities bei einer Störung
    # nicht verschwinden, sondern nur unavailable werden.
    daten = dict(entry.data)
    bekannt = set(daten.get(CONF_KNOWN_NUMBERS) or []) | set(coordinator.data or {})
    if set(daten.get(CONF_KNOWN_NUMBERS) or []) != bekannt:
        daten[CONF_KNOWN_NUMBERS] = sorted(bekannt)
        hass.config_entries.async_update_entry(entry, data=daten)

    registry = dr.async_get(hass)
    hub = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, info["seriennummer"])},
        name=info["name"],
        manufacturer=info["hersteller"],
        model=info["modell"],
        configuration_url=f"http://{host}",
    )
    # Die Geraete je Rufnummer hier anlegen statt ueber DeviceInfo(via_device=...)
    # in den Entities: via_device ist deprecated, via_device_id braucht die id des
    # bereits angelegten Hub-Geraets.
    for nummer in sorted(bekannt):
        eintrag = (coordinator.data or {}).get(nummer, {})
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{info['seriennummer']}-{nummer}")},
            name=eintrag.get("name") or nummer,
            manufacturer=eintrag.get("registrar") or info["hersteller"],
            model=eintrag.get("typ") or "VoIP",
            via_device_id=hub.id,
        )

    coordinator.geraet = info
    dect: FritzDectCoordinator | None = None
    if info["dect"]:
        dect = FritzDectCoordinator(hass, entry)
        dect.geraet = info
        await dect.async_config_entry_first_refresh()

    entry.runtime_data = FritzNumbersData(
        nummern=coordinator, mobilteile=dect, geraet=info, hub_id=hub.id
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class _FritzCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Pollt eine Abruffunktion und überbrückt kurze Störungen."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        name: str,
        intervall: int,
        karenz: int,
        abruf: Callable[[str, str, str], dict[str, dict[str, Any]]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=name,
            update_interval=timedelta(seconds=intervall),
        )
        self._host = entry.data[CONF_HOST]
        self._user = entry.data[CONF_USERNAME]
        self._pw = entry.data[CONF_PASSWORD]
        self._karenz = karenz
        self._abruf = abruf
        self._last_ok = 0.0
        self.geraet: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            daten = await self.hass.async_add_executor_job(
                self._abruf, self._host, self._user, self._pw
            )
        except FritzVoipAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FritzVoipError as err:
            if self.data is not None and time.monotonic() - self._last_ok < self._karenz:
                _LOGGER.warning("TR-064-Abruf fehlgeschlagen, nutze letzte Werte: %s", err)
                return self.data
            raise UpdateFailed(str(err)) from err
        self._last_ok = time.monotonic()
        return daten


class FritzVoipCoordinator(_FritzCoordinator):
    """Registrierungszustand der Rufnummern, alle fünf Minuten."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, DOMAIN, UPDATE_INTERVAL, GRACE_SECONDS, rufnummern)


class FritzDectCoordinator(_FritzCoordinator):
    """DECT-Mobilteile im kurzen Takt, damit Gespräche nicht durchrutschen."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, entry, f"{DOMAIN}_dect", DECT_UPDATE_INTERVAL, DECT_GRACE_SECONDS, mobilteile
        )
