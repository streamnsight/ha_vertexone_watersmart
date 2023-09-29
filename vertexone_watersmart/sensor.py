"""WaterSmart sensors."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, List, Optional

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import SCWSCoordinator, ENTITIES, SCWSEntityDescription

from enum import StrEnum

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensors."""

    _LOGGER.debug(f"entry: {entry}")
    coordinator: SCWSCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SCWSSensor] = []
    devices = coordinator.data.values()
    _LOGGER.debug(devices)

    for d in devices:
        device_id = f"_scmu"
        device = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=f"{NAME} {d}",
            manufacturer="WaterSmart",
            model="Water",
            entry_type=DeviceEntryType.SERVICE,
        )

        for entity in ENTITIES:
            entities.append(
                SCWSSensor(
                    coordinator,
                    entity,
                    device,
                    device_id,
                )
            )

    async_add_entities(entities)


class SCWSSensor(CoordinatorEntity[SCWSCoordinator], SensorEntity):
    """Representation of a sensor."""

    entity_description: SCWSEntityDescription

    def __init__(
        self,
        coordinator: SCWSCoordinator,
        description: SCWSEntityDescription,
        device: DeviceInfo,
        device_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_device_info = device
        self._attr_should_poll = False

    @property
    def native_value(self) -> StateType:
        """Return the state."""
        # Return None so as not to pollute the state with data we don't have.
        return None

    @property
    def state(self) -> StateType:
        """Return the state."""
        # Return None so as not to pollute the state with data we don't have.
        return None
