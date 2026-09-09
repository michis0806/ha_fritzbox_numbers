"""Config-Flow für FritzBox Rufnummern."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

from . import FritzVoipAuthError, FritzVoipError, geraetedaten, rufnummern
from .const import DOMAIN

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="fritz.box"): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class FritzVoipConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _pruefen(self, daten: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
        """Verbindung testen. Gibt (Gerätedaten, Fehler) zurück."""
        try:
            info = await self.hass.async_add_executor_job(geraetedaten, daten[CONF_HOST])
            await self.hass.async_add_executor_job(
                rufnummern, daten[CONF_HOST], daten[CONF_USERNAME], daten[CONF_PASSWORD]
            )
        except FritzVoipAuthError:
            return {}, {"base": "invalid_auth"}
        except FritzVoipError as err:
            return {}, {"base": "no_tr064" if "TR-064" in str(err) else "cannot_connect"}
        return info, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            info, errors = await self._pruefen(user_input)
            if not errors:
                await self.async_set_unique_id(info["seriennummer"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["name"], data=user_input)
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            neu = {**entry.data, **user_input}
            _, errors = await self._pruefen(neu)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=neu)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                 vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )
