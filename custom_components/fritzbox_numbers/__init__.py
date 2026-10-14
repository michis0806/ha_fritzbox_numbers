"""FritzBox Rufnummern — Registrierungsstatus der VoIP-Nummern über TR-064.

Die offizielle fritz-Integration (FRITZ!Box Tools) liefert Verbindungsstatus,
Bandbreite und Anwesenheitserkennung, aber nicht den Registrierungszustand der
Rufnummern. Diese Integration fragt dafür den Dienst X_VoIP:1 ab, dazu die
DECT-Mobilteile über X_AVM-DE_Dect:1, die Anrufliste über X_AVM-DE_OnTel:1 und
die Anrufbeantworter über X_AVM-DE_TAM:1.

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
from datetime import datetime, timedelta
from functools import partial
from typing import Any
from xml.sax.saxutils import escape, unescape

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ANRUFLISTE_MAX,
    CONF_KNOWN_NUMBERS,
    CONTROL_PATH,
    DECT_CONTROL_PATH,
    DECT_GRACE_SECONDS,
    DECT_SERVICE,
    DECT_UPDATE_INTERVAL,
    DESC_PATH,
    DOMAIN,
    GRACE_SECONDS,
    ONTEL_CONTROL_PATH,
    ONTEL_SERVICE,
    REQUEST_TIMEOUT,
    SERVICE,
    STATUS_REGISTERED,
    TAM_CONTROL_PATH,
    TAM_SERVICE,
    TELEFONIE_GRACE_SECONDS,
    TELEFONIE_UPDATE_INTERVAL,
    TR064_PORT,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor", "switch"]

VOIP = (SERVICE, CONTROL_PATH)
DECT = (DECT_SERVICE, DECT_CONTROL_PATH)
ONTEL = (ONTEL_SERVICE, ONTEL_CONTROL_PATH)
TAM = (TAM_SERVICE, TAM_CONTROL_PATH)

# Call-Typen der Anrufliste laut AVM-Doku zu X_AVM-DE_OnTel
ANRUFTYPEN = {
    "1": "eingehend",
    "2": "verpasst",
    "3": "ausgehend",
    "9": "eingehend_aktiv",
    "10": "abgewiesen",
    "11": "ausgehend_aktiv",
}
AUSGEHEND = {"3", "11"}


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
        # Boxen ohne DECT-Basis oder Anrufbeantworter bieten den Dienst gar nicht an
        "dect": DECT_SERVICE in xml,
        "anrufliste": ONTEL_SERVICE in xml,
        "ab": TAM_SERVICE in xml,
    }


def _liste_laden(host: str, ziel: str, was: str) -> str:
    """Eine XML-Liste laden, deren URL (mit Session-ID) ein SOAP-Aufruf geliefert hat.

    Manche Aufrufe liefern nur den Pfad, andere die volle URL. Die URL enthält die
    Session-ID und gehört deshalb nicht in Fehlermeldungen oder ins Log.
    """
    url = f"http://{host}:{TR064_PORT}{ziel}" if ziel.startswith("/") else ziel
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        raise FritzVoipError(f"HTTP {err.code} beim Lesen der {was}") from err
    except OSError as err:
        raise FritzVoipError(f"{host} nicht erreichbar: {err}") from err


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
    Sessions an.
    """
    pfad = _feld(soap(host, user, pw, "GetDectListPath", dienst=DECT), "NewDectListPath")
    if not pfad:
        raise FritzVoipError("Box liefert keinen Pfad zur DECT-Liste")
    xml = _liste_laden(host, pfad, "DECT-Liste")

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


def _zeit(text: str | None) -> datetime | None:
    """Datum der Box ("14.10.26 22:12", Ortszeit) als aware datetime."""
    try:
        return datetime.strptime(text or "", "%d.%m.%y %H:%M").replace(
            tzinfo=dt_util.get_default_time_zone()
        )
    except ValueError:
        return None


def _minuten(text: str | None) -> int | None:
    """Dauer der Box ("1:05" = Stunden:Minuten) in Minuten."""
    stunden, _, minuten = (text or "").partition(":")
    if not (stunden.isdigit() and minuten.isdigit()):
        return None
    return int(stunden) * 60 + int(minuten)


def _ziffern(nummer: str) -> str:
    """Nummer ohne Zeichen, Ländervorwahl +49/0049 als führende 0."""
    ziffern = re.sub(r"\D", "", nummer)
    if nummer.strip().startswith("+") and ziffern.startswith("49"):
        return "0" + ziffern[2:]
    if ziffern.startswith("0049"):
        return "0" + ziffern[4:]
    return ziffern


def gleiche_nummer(a: str | None, b: str | None) -> bool:
    """Ob zwei Schreibweisen dieselbe Rufnummer meinen.

    Je nach Anbieter führt die Anrufliste die eigene Nummer mit oder ohne
    Vorwahl, deshalb genügt es, wenn die kürzere das Ende der längeren ist.
    """
    x, y = _ziffern(a or ""), _ziffern(b or "")
    if not x or not y:
        return False
    kurz, lang = sorted((x, y), key=len)
    return lang.endswith(kurz) and len(kurz) >= 5


def anrufliste(host: str, user: str, pw: str) -> list[dict[str, Any]]:
    """Die letzten Anrufe, neueste zuerst."""
    url = _feld(soap(host, user, pw, "GetCallList", dienst=ONTEL), "NewCallListURL")
    if not url:
        raise FritzVoipError("Box liefert keine URL zur Anrufliste")
    xml = _liste_laden(host, f"{url}&max={ANRUFLISTE_MAX}", "Anrufliste")

    anrufe = []
    for call in _bloecke(xml, "Call"):
        typ = call.get("Type", "")
        # Gegenstelle und eigene Nummer stehen je nach Richtung in anderen Feldern
        if typ in AUSGEHEND:
            nummer, eigene = call.get("Called"), call.get("CallerNumber")
        else:
            nummer, eigene = call.get("Caller"), call.get("CalledNumber")
        anrufe.append(
            {
                "typ": ANRUFTYPEN.get(typ, typ),
                "zeit": _zeit(call.get("Date")),
                "nummer": nummer or None,
                "name": (call.get("Name") or "").strip() or None,
                "eigene_nummer": eigene or None,
                "mobilteil": call.get("Device") or None,
                "dauer_min": _minuten(call.get("Duration")),
            }
        )
    return anrufe


def anrufbeantworter(host: str, user: str, pw: str) -> dict[str, dict[str, Any]]:
    """Eingerichtete Anrufbeantworter mit ihren Nachrichten.

    Die Box hat immer fünf AB-Plätze. Leere Plätze (nicht angezeigt, aus und ohne
    Namen) werden übersprungen.
    """
    liste = _feld(soap(host, user, pw, "GetList", dienst=TAM), "NewTAMList") or ""
    ergebnis: dict[str, dict[str, Any]] = {}
    for item in _bloecke(liste, "Item"):
        name = (item.get("Name") or "").strip()
        index = item.get("Index", "")
        if not index or not (item.get("Display") == "1" or item.get("Enable") == "1" or name):
            continue
        url = _feld(
            soap(host, user, pw, "GetMessageList", {"NewIndex": index}, dienst=TAM), "NewURL"
        )
        nachrichten = _bloecke(_liste_laden(host, url, "Nachrichtenliste"), "Message") if url else []
        neu = [n for n in nachrichten if n.get("New") == "1"]
        letzte = max(
            neu,
            key=lambda n: _zeit(n.get("Date")) or datetime.min.replace(tzinfo=dt_util.UTC),
            default=None,
        )
        ergebnis[index] = {
            "index": index,
            "name": name,
            "aktiv": item.get("Enable") == "1",
            "nachrichten": len(nachrichten),
            "neu": len(neu),
            "letzte_neue": None
            if letzte is None
            else {
                "zeit": _zeit(letzte.get("Date")),
                "nummer": letzte.get("Number") or None,
                "name": (letzte.get("Name") or "").strip() or None,
                "dauer_min": _minuten(letzte.get("Duration")),
            },
        }
    return ergebnis


def telefonie(
    host: str, user: str, pw: str, mit_anrufliste: bool, mit_ab: bool
) -> dict[str, Any]:
    """Anrufliste und Anrufbeantworter in einem Abruf."""
    return {
        "anrufe": anrufliste(host, user, pw) if mit_anrufliste else None,
        "ab": anrufbeantworter(host, user, pw) if mit_ab else {},
    }


@dataclass
class FritzNumbersData:
    """Was eine eingerichtete Box zur Laufzeit an ihre Plattformen weitergibt."""

    nummern: FritzVoipCoordinator
    mobilteile: FritzDectCoordinator | None
    telefonie: FritzTelefonieCoordinator | None
    geraet: dict[str, Any]
    hub_id: str


def _untergeraet(
    hass: HomeAssistant,
    entry: ConfigEntry,
    daten: FritzNumbersData,
    kennung: str,
    name: str,
    modell: str,
) -> None:
    """Ein Gerät unterhalb der Box anlegen oder auffrischen."""
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{daten.geraet['seriennummer']}-{kennung}")},
        name=name,
        manufacturer=daten.geraet["hersteller"],
        model=modell,
        via_device_id=daten.hub_id,
    )


def mobilteil_geraet(
    hass: HomeAssistant, entry: ConfigEntry, daten: FritzNumbersData, eintrag: dict[str, Any]
) -> None:
    """Das Gerät eines Mobilteils unterhalb der Box anlegen oder auffrischen."""
    _untergeraet(
        hass,
        entry,
        daten,
        f"dect-{eintrag['id']}",
        eintrag.get("name") or f"Mobilteil {eintrag['id']}",
        eintrag.get("modell") or "DECT",
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

    tel: FritzTelefonieCoordinator | None = None
    if info["anrufliste"] or info["ab"]:
        tel = FritzTelefonieCoordinator(hass, entry, info["anrufliste"], info["ab"])
        tel.geraet = info
        await tel.async_config_entry_first_refresh()

    laufzeit = FritzNumbersData(
        nummern=coordinator, mobilteile=dect, telefonie=tel, geraet=info, hub_id=hub.id
    )
    # Die AB-Plaetze stehen fest, ihre Geraete koennen gleich hier entstehen
    for ab in (tel.data["ab"] if tel else {}).values():
        _untergeraet(
            hass,
            entry,
            laufzeit,
            f"tam-{ab['index']}",
            ab["name"] or f"Anrufbeantworter {int(ab['index']) + 1}",
            "Anrufbeantworter",
        )

    entry.runtime_data = laufzeit
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class _FritzCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Pollt eine Abruffunktion und überbrückt kurze Störungen."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        name: str,
        intervall: int,
        karenz: int,
        abruf: Callable[[str, str, str], dict[str, Any]],
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

    async def _async_update_data(self) -> dict[str, Any]:
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


class FritzTelefonieCoordinator(_FritzCoordinator):
    """Anrufliste und Anrufbeantworter, einmal pro Minute."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, mit_anrufliste: bool, mit_ab: bool
    ) -> None:
        super().__init__(
            hass,
            entry,
            f"{DOMAIN}_telefonie",
            TELEFONIE_UPDATE_INTERVAL,
            TELEFONIE_GRACE_SECONDS,
            partial(telefonie, mit_anrufliste=mit_anrufliste, mit_ab=mit_ab),
        )

    async def ab_schalten(self, index: str, an: bool) -> None:
        """Einen Anrufbeantworter ein- oder ausschalten und neu einlesen."""
        try:
            await self.hass.async_add_executor_job(
                partial(
                    soap,
                    self._host,
                    self._user,
                    self._pw,
                    "SetEnable",
                    {"NewIndex": index, "NewEnable": int(an)},
                    dienst=TAM,
                )
            )
        except FritzVoipError as err:
            raise HomeAssistantError(f"Anrufbeantworter nicht geschaltet: {err}") from err
        await self.async_request_refresh()
