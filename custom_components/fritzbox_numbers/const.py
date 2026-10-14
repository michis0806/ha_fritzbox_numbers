"""Konstanten für FritzBox Rufnummern."""

DOMAIN = "fritzbox_numbers"

TR064_PORT = 49000
DESC_PATH = "/tr64desc.xml"
CONTROL_PATH = "/upnp/control/x_voip"
SERVICE = "urn:dslforum-org:service:X_VoIP:1"
DECT_CONTROL_PATH = "/upnp/control/x_dect"
DECT_SERVICE = "urn:dslforum-org:service:X_AVM-DE_Dect:1"

CONF_KNOWN_NUMBERS = "known_numbers"

UPDATE_INTERVAL = 300   # Sekunden
GRACE_SECONDS = 1800    # bei Störung alte Werte max. 30 Min weiterreichen
REQUEST_TIMEOUT = 15

# Mobilteile kurz takten, sonst entgehen dem Gesprächs-Sensor kurze Anrufe
DECT_UPDATE_INTERVAL = 15  # Sekunden
DECT_GRACE_SECONDS = 60

STATUS_REGISTERED = "registered"
