"""Konstanten für FritzBox Rufnummern."""

DOMAIN = "fritzbox_numbers"

TR064_PORT = 49000
DESC_PATH = "/tr64desc.xml"
CONTROL_PATH = "/upnp/control/x_voip"
SERVICE = "urn:dslforum-org:service:X_VoIP:1"

CONF_KNOWN_NUMBERS = "known_numbers"

UPDATE_INTERVAL = 300   # Sekunden
GRACE_SECONDS = 1800    # bei Störung alte Werte max. 30 Min weiterreichen
REQUEST_TIMEOUT = 15

STATUS_REGISTERED = "registered"
