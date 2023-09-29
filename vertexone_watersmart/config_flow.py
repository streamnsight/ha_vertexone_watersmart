"""Config flow for Watersmart integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from vertexone_watersmart.client import Client
from vertexone_watersmart.exceptions import (
    NotAuthenticatedException,
    UnauthorizedException,
    UnknownException,
)
from vertexone_watersmart.providers import PROVIDER_LIST

from .const import DOMAIN, CONF_DISTRICT_NAME


_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DISTRICT_NAME): vol.In(sorted([v for _, v in PROVIDER_LIST.items()])),
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _validate_login(
    hass: HomeAssistant, login_data: dict[str, str]
) -> dict[str, str]:
    """Validate login data and return any errors."""
    providers = {v: k for k, v in PROVIDER_LIST.items()}
    provider = providers[login_data[CONF_DISTRICT_NAME]]
    api = Client(provider=provider, is_async=True)
    errors: dict[str, str] = {}
    try:
        await api.login(login_data[CONF_USERNAME], login_data[CONF_PASSWORD])
    except UnauthorizedException:
        errors["base"] = "invalid_auth"
    except NotAuthenticatedException:
        errors["base"] = "invalid_auth"
    except UnknownException:
        errors["base"] = "cannot_connect"
    return errors


class SCWSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Watersmart."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize a new ConfigFlow."""
        self.reauth_entry: config_entries.ConfigEntry | None = None
        self.utility_info: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user credentials step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(
                {
                    CONF_DISTRICT_NAME: user_input[CONF_DISTRICT_NAME],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                }
            )

            errors = await _validate_login(self.hass, user_input)
            if not errors:
                return self._async_create_config_entry(user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @callback
    def _async_create_config_entry(self, data: dict[str, Any]) -> FlowResult:
        """Create the config entry."""
        return self.async_create_entry(
            title=f"{data[CONF_DISTRICT_NAME]} WaterSmart ({data[CONF_USERNAME]})",
            data=data,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle configuration by re-auth."""
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Dialog that informs the user that re-authentication is required."""
        assert self.reauth_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self.reauth_entry.data, **user_input}
            errors = await _validate_login(self.hass, data)
            if not errors:
                self.hass.config_entries.async_update_entry(
                    self.reauth_entry, data=data
                )
                await self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        schema = {
            vol.Required(CONF_USERNAME): self.reauth_entry.data[CONF_USERNAME],
            vol.Required(CONF_PASSWORD): str,
        }
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(schema),
            errors=errors,
        )
