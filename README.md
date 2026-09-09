# FritzBox Numbers (`fritzbox_numbers`)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=michis0806&repository=ha_fritzbox_numbers&category=integration)
[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=fritzbox_numbers)

Home Assistant custom integration that shows whether the **phone numbers of a
FRITZ!Box are registered** with their VoIP provider — one device per number.

[Deutsche Beschreibung weiter unten.](#deutsch)

## What it does

The official [FRITZ!Box Tools integration](https://www.home-assistant.io/integrations/fritz/)
covers connection state, bandwidth, presence detection, Wi-Fi switches and call
deflections — but **not** whether your phone numbers are actually registered. This
integration fills that gap by querying the TR-064 service `X_VoIP:1` and creates:

- one **device per phone number** (below the FRITZ!Box hub device),
- a **connectivity** binary sensor per number — on while the number is registered,
- a **registration status** sensor per number carrying the raw status text reported
  by the box (`registered`, `unregistered`, …), as a diagnostic entity,
- a **registered numbers** sensor on the box itself, counting the registered
  numbers and listing the unregistered ones in an attribute.

## Requirements

- **"Allow access for applications" (TR-064)** enabled on the FRITZ!Box, under
  *Home Network → Network → Network Settings*. "Transmit status information over
  UPnP" is **not** needed.
- A FRITZ!Box user account with the **"FRITZ!Box Settings"** permission.

If TR-064 is off, `http://<box>:49000/tr64desc.xml` answers `404` even though port
49000 is open — that is the quickest way to check.

## Installation

### HACS (custom repository)

Click the HACS badge above, or manually:

1. HACS → Integrations → ⋮ → *Custom repositories*
2. Add `https://github.com/michis0806/ha_fritzbox_numbers` (category: Integration)
3. Install **FritzBox Numbers** and restart Home Assistant.

### Manual

Copy `custom_components/fritzbox_numbers/` into your `config/custom_components/` folder
and restart Home Assistant.

## Setup

Settings → Devices & services → *Add integration* → **FritzBox Numbers**, then enter
host, username and password. The box serial number is used as the unique ID, so the
same box cannot be added twice. If the credentials stop working later, Home
Assistant offers the usual re-authentication dialog.

## Behavior on outages

Numbers are polled every 5 minutes. If the box is temporarily unreachable, the last
known values are kept for up to 30 minutes before entities become `unavailable`.
Numbers that have been seen once are remembered, so their entities do not disappear
during an outage.

## Notes

TR-064 requires HTTP digest authentication, which `aiohttp` does not support. The
requests therefore run through `urllib` in the executor rather than asynchronously —
uncritical at one poll every five minutes, and it avoids a dependency on
`fritzconnection`.

## Disclaimer

This project is not affiliated with AVM. Use at your own risk.

---

## Deutsch

Home-Assistant-Integration, die zeigt, ob die **Rufnummern einer FRITZ!Box beim
VoIP-Anbieter registriert** sind — ein Gerät pro Rufnummer. Die offizielle
FRITZ!Box-Tools-Integration liefert diese Information nicht.

- Benötigt **"Zugriff für Anwendungen zulassen"** (TR-064) in der FritzBox unter
  *Heimnetz → Netzwerk → Netzwerkeinstellungen*. UPnP-Statusinformationen werden
  **nicht** gebraucht.
- Der FritzBox-Benutzer braucht die Berechtigung **"FRITZ!Box Einstellungen"**.
- Installation über HACS (Custom Repository) oder manuell nach
  `config/custom_components/`, danach Neustart.
- Einrichtung über *Integration hinzufügen* → **FritzBox Numbers** mit Host,
  Benutzer und Passwort.

Je Rufnummer entstehen ein Verbindungs-Binärsensor und ein Diagnose-Sensor mit dem
unveränderten Statustext der Box; an der Box selbst zählt ein Sensor die
registrierten Rufnummern und listet die nicht verbundenen als Attribut.

**Schnelltest, ob TR-064 an ist:** `http://<box>:49000/tr64desc.xml`. Kommt dort ein
`404`, obwohl Port 49000 offen ist, ist die Anwendungsschnittstelle abgeschaltet.

Bei Störungen werden die letzten Werte bis zu 30 Minuten weitergereicht.
