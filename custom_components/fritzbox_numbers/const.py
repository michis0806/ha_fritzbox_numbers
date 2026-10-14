"""Konstanten für FritzBox Rufnummern."""

DOMAIN = "fritzbox_numbers"

TR064_PORT = 49000
DESC_PATH = "/tr64desc.xml"
CONTROL_PATH = "/upnp/control/x_voip"
SERVICE = "urn:dslforum-org:service:X_VoIP:1"
DECT_CONTROL_PATH = "/upnp/control/x_dect"
DECT_SERVICE = "urn:dslforum-org:service:X_AVM-DE_Dect:1"
ONTEL_CONTROL_PATH = "/upnp/control/x_contact"
ONTEL_SERVICE = "urn:dslforum-org:service:X_AVM-DE_OnTel:1"
TAM_CONTROL_PATH = "/upnp/control/x_tam"
TAM_SERVICE = "urn:dslforum-org:service:X_AVM-DE_TAM:1"

CONF_KNOWN_NUMBERS = "known_numbers"

UPDATE_INTERVAL = 300   # Sekunden
GRACE_SECONDS = 1800    # bei Störung alte Werte max. 30 Min weiterreichen
REQUEST_TIMEOUT = 15

# Mobilteile kurz takten, sonst entgehen dem Gesprächs-Sensor kurze Anrufe
DECT_UPDATE_INTERVAL = 15  # Sekunden
DECT_GRACE_SECONDS = 60

# Anrufliste und Anrufbeantworter
TELEFONIE_UPDATE_INTERVAL = 60  # Sekunden
TELEFONIE_GRACE_SECONDS = 600
ANRUFLISTE_MAX = 100  # reicht für "verpasst heute", die Box hält bis zu 400

STATUS_REGISTERED = "registered"
