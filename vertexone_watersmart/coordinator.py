"""Coordinator to handle Watersmart connections."""
import itertools
import logging
import statistics
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, cast
from dataclasses import dataclass

from homeassistant.components.recorder.db_schema import (
    States,
)
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
)
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.sensor.const import SensorDeviceClass, SensorStateClass

from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    UnitOfTemperature,
    UnitOfVolume,
    UnitOfVolumetricFlux,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from vertexone_watersmart.client import Client
from vertexone_watersmart.providers import PROVIDER_LIST

from .const import DOMAIN, NAME, CONF_DISTRICT_NAME
from .utils import (
    TimeBlocs,
    get_or_create,
    save_states,
    get_last_known_state,
    get_last_known_statistic,
    delete_invalid_states,
)
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


@dataclass
class V1WSEntityDescriptionMixin:
    """Mixin values for required keys."""

    api_value_key: str
    period: str

    def value_fn(self, data):
        return data[self.api_value_key]


@dataclass
class V1WSEntityDescription(SensorEntityDescription, V1WSEntityDescriptionMixin):
    """Class describing sensors entities."""


ENTITIES: list[V1WSEntityDescription] = [
    V1WSEntityDescription(
        key="hourly_water_consumption",
        name="Hourly Water Consumption",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        period="hourly",
        api_value_key="gallons",
    ),
    V1WSEntityDescription(
        key="hourly_water_leak",
        name="Hourly Water Leak",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        period="hourly",
        api_value_key="leak_gallons",
    ),
    V1WSEntityDescription(
        key="hourly_water_leak_computed",
        name="Hourly Water Leak (Computed)",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        period="hourly",
        api_value_key="gallons",
    ),
    V1WSEntityDescription(
        key="daily_water_consumption",
        name="Daily Water Consumption",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        period="daily",
        api_value_key="consumption",
    ),
    V1WSEntityDescription(
        key="daily_temperature",
        name="Daily Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        period="daily",
        api_value_key="temperature",
    ),
    V1WSEntityDescription(
        key="daily_precipitation",
        name="Daily Precipitation",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfVolumetricFlux.INCHES_PER_DAY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        period="daily",
        api_value_key="precipitation",
    ),
]


class V1WSCoordinator(DataUpdateCoordinator[dict[str, object]]):
    """Handle fetching data, updating sensors and inserting statistics."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_data: MappingProxyType[str, Any],
    ) -> None:
        """Initialize the data handler."""
        self.update_interval = timedelta(hours=6)
        super().__init__(
            hass,
            _LOGGER,
            name=NAME,
            # Data is updated every 12 to 24h.
            # Refresh every 6h.
            update_interval=self.update_interval,  # set to 2 hours
            update_method=self.update_data,
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=0.3, immediate=True, function=self.update_data
            ),
        )

        providers = {v: k for k, v in PROVIDER_LIST.items()}
        provider = providers[entry_data[CONF_DISTRICT_NAME]]

        self.api = Client(provider=provider, is_async=True)
        self.account = entry_data[CONF_USERNAME]
        self.entry_data = entry_data

    async def update_data(self) -> dict[str, object]:
        """Fetch data from API endpoint."""
        t0 = datetime.now()
        datapoints = {}

        states = []
        old_states = {}
        state_meta_ids = {}
        stats = {}
        stats_meta_ids = {}
        stats_meta = {}
        last_states = {}
        last_stats = {}
        sensor_period_type = list(set([s.period for s in ENTITIES]))

        for entity_type in sensor_period_type:
            retry = 3
            while retry >= 0:
                try:
                    await self.api.login(
                        self.entry_data[CONF_USERNAME], self.entry_data[CONF_PASSWORD]
                    )
                    break
                except Exception as e:
                    _LOGGER.debug(e)
                    retry -= 1
            if retry < 0:
                _LOGGER.error("Failed to login to vertexone watersmart")
                continue
            # get the api according to the period (daily or hourly).
            # The API provides 1 year+ of data every time.
            api = getattr(self.api, entity_type)
            retry = 3
            while retry >= 0:
                try:
                    t1 = datetime.now()
                    datapoints[entity_type] = await api.fetch()
                    _LOGGER.debug("fetch data took %s", datetime.now() - t1)
                    break
                except Exception as e:
                    _LOGGER.debug(e)
                    retry -= 1
            if retry < 0:
                _LOGGER.error("Failed to fetch data for vertexone watersmart")
                continue
            entities = [e for e in ENTITIES if e.period == entity_type]

            for entity in entities:
                t1 = datetime.now()
                state_meta_ids[entity.key] = await get_or_create(
                    self.hass, id=f"sensor.{entity.key}"
                )
                _LOGGER.debug(
                    "get %s metadata took %s",
                    f"sensor.{entity.key}",
                    datetime.now() - t1,
                )
                t1 = datetime.now()
                last_states[entity.key] = await get_last_known_state(
                    self.hass, f"sensor.{entity.key}"
                )
                _LOGGER.debug(
                    "get %s last state took %s",
                    f"sensor.{entity.key}",
                    datetime.now() - t1,
                )

                t1 = datetime.now()
                last_stats[entity.key] = await get_last_known_statistic(
                    self.hass, f"sensor.{entity.key}"
                )
                _LOGGER.debug(
                    "get %s last stat took %s",
                    f"sensor.{entity.key}",
                    datetime.now() - t1,
                )

                t1 = datetime.now()
                await delete_invalid_states(self.hass, state_meta_ids[entity.key])
                _LOGGER.debug("delete invalid states took %s", datetime.now() - t1)

            dataset = datapoints[entity_type]
            last_values = []

            # record historical sensor states, to be visible as a sensor history, not only statistics.
            last_idx = 1

            t1 = datetime.now()
            for i, d in enumerate(dataset):
                offset = datetime.fromtimestamp(
                    d["ts"], tz=dt_util.DEFAULT_TIME_ZONE
                ) - datetime.fromtimestamp(d["ts"], tz=timezone.utc)
                dt1 = datetime.fromtimestamp(d["ts"], tz=timezone.utc)
                # + offset
                dt1 = datetime.fromtimestamp(d["ts"], tz=timezone.utc).replace(
                    tzinfo=None
                )
                dt2 = dt_util.as_local(dt1)
                # ts needs to be corrected as it is a non-standard unix timestamp. It includes a timezone offset
                # so that the UTC timestamp is actually the time in the local timezone.
                # We load it as a UTC timestamp so it is not changed, then strip the timezone info
                # and transform it to a localized datetime.
                # to get a real UTC timestamp.
                ts = dt_util.as_local(
                    datetime.fromtimestamp(d["ts"], tz=timezone.utc).replace(
                        tzinfo=None
                    )
                ).timestamp()
                if i == 0:
                    _LOGGER.debug(
                        "orig_ts: %s, fromts: %s, localdt: %s, ts: %s, tz: %s",
                        d["ts"],
                        dt1,
                        dt2,
                        ts,
                        dt_util.DEFAULT_TIME_ZONE,
                    )

                for entity in entities:
                    # skip records that have already been seen.
                    if entity.key not in old_states:
                        old_states[entity.key] = last_states[entity.key]

                    if (
                        last_states[entity.key]["last_changed_ts"] is not None
                        and ts <= last_states[entity.key]["last_changed_ts"]
                    ):
                        last_idx += 1
                        continue

                    if entity.key == "hourly_water_leak_computed":
                        last_values.append(d[entity.api_value_key])
                        # trim last values set
                        last_values = last_values[-5:]
                        state = min(last_values)
                    else:
                        state = d[entity.api_value_key]

                    new_state = States(
                        state=state,
                        metadata_id=state_meta_ids[entity.key],
                        last_changed_ts=ts,
                        last_updated_ts=ts,
                        old_state=old_states[entity.key] if i >= last_idx else None,
                    )

                    states.append(new_state)
                    old_states[entity.key] = new_state

            _LOGGER.debug("parsing data to states took %s", datetime.now() - t1)

            t1 = datetime.now()
            # save states and build statistics.
            for entity in entities:
                t1 = datetime.now()
                if entity.key not in stats_meta:
                    stats_meta[entity.key] = {}
                if entity.key not in stats:
                    stats[entity.key] = {}

                # build stats
                stats[entity.key] = []
                stats_meta[entity.key] = StatisticMetaData(
                    has_mean=True,
                    has_sum=True,
                    name=entity.name,
                    source="recorder",
                    statistic_id=f"sensor.{entity.key}",
                    unit_of_measurement=entity.native_unit_of_measurement,
                )

                accumulated = 0
                for dt, collection_it in itertools.groupby(
                    dataset, key=TimeBlocs(entity_type).fn
                ):
                    if (
                        last_stats[entity.key] is not None
                        and dt.timestamp() <= last_stats[entity.key]["start"]
                    ):
                        continue
                    dttt = dt.timetuple()
                    if (dttt.tm_hour == 0 and entity_type == "daily") or (
                        dttt.tm_min == 0 and entity_type == "hourly"
                    ):
                        accumulated = 0
                    collection = list(collection_it)
                    values = [
                        x[entity.api_value_key]
                        for x in collection
                        if x[entity.api_value_key] is not None
                    ]
                    mean = 0
                    if len(values) > 0:
                        mean = statistics.mean(values)
                    partial_sum = sum(values)
                    accumulated = accumulated + partial_sum

                    stats[entity.key].append(
                        StatisticData(
                            start=dt,
                            # end=end_time,
                            state=partial_sum,
                            mean=mean,
                            sum=accumulated,
                            last_reset=dt,
                        )
                    )
                _LOGGER.debug(
                    "parsing %s stats took %s",
                    f"sensor.{entity.key}",
                    datetime.now() - t1,
                )

                t1 = datetime.now()
                if len(stats[entity.key]) > 0:
                    async_import_statistics(
                        self.hass,
                        stats_meta[entity.key],
                        stats[entity.key],
                    )
                _LOGGER.debug(
                    "storing %s stats took %s",
                    f"sensor.{entity.key}",
                    datetime.now() - t1,
                )
            if len(states) > 0:
                t1 = datetime.now()
                await save_states(self.hass, states)
                _LOGGER.debug(
                    "saving state took %s",
                    datetime.now() - t1,
                )

            _LOGGER.debug(
                f"Updated {entity_type} with {len(stats[entity.key])} entries in {datetime.now() - t0}."
            )
        _LOGGER.debug(f"Next poll at {datetime.now() + self.update_interval}.")

        return {self.account: {}}
