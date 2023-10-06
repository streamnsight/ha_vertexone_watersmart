from datetime import datetime, timedelta, timezone
from sqlalchemy import or_

from homeassistant.components import recorder
from homeassistant.components.recorder.db_schema import (
    States,
    StatesMeta,
    StatisticsMeta,
    StatisticsBase,
)

from homeassistant.components.recorder.statistics import (
    StatisticsRow,
    get_last_statistics,
)

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from homeassistant.util import dt as dt_util


def _get_or_create(session, entity_id):
    instance = session.query(StatesMeta).filter_by(entity_id=entity_id).first()
    if not instance:
        instance = StatesMeta(entity_id=entity_id)
        session.add(instance)
        session.commit()
    return instance.metadata_id


async def delete_invalid_states(hass, id):
    r = recorder.get_instance(hass)
    with recorder.util.session_scope(session=r.get_session()) as session:
        await r.async_add_executor_job(_delete_invalid_states, session, id)


def _delete_invalid_states(session, entity_id):
    to_delete = session.query(States).where(
        or_(States.state == STATE_UNKNOWN, States.state == STATE_UNAVAILABLE)
    )
    try:
        to_delete.delete()
        session.commit()
    except Exception:
        session.flush()
        session.expunge_all()
        session.commit()
        pass


async def get_or_create(hass, id):
    r = recorder.get_instance(hass)
    with recorder.util.session_scope(session=r.get_session()) as session:
        instance = await r.async_add_executor_job(_get_or_create, session, id)
    return instance


def _save_states(session, states):
    session.bulk_save_objects(states)
    # session.add_all(states)
    session.commit()


async def save_states(hass, states):
    r = recorder.get_instance(hass)
    with recorder.util.session_scope(session=r.get_session()) as session:
        res = await r.async_add_executor_job(_save_states, session, states)
    return res


def _get_last_known_state(session, entity_id) -> States:
    return (
        session.query(States)
        .join(StatesMeta)
        .where(StatesMeta.entity_id == entity_id)
        .order_by(States.last_changed_ts.desc())
        .first()
    )


async def get_last_known_state(hass, metadata_id) -> States:
    r = recorder.get_instance(hass)
    with recorder.util.session_scope(session=r.get_session()) as session:
        instance = await r.async_add_executor_job(
            _get_last_known_state, session, metadata_id
        )
        if instance is not None:
            return {"last_changed_ts": instance.last_changed_ts}
        return {"last_changed_ts": None}


def _get_last_known_statistic(session, metadata_id) -> StatisticsBase:
    return (
        session.query(StatisticsBase)
        .filter_by(metadata_id=metadata_id)
        .order_by(StatisticsBase.start.desc())
        .first()
    )


async def get_last_known_statistic(hass, statistic_id):
    r = recorder.get_instance(hass)
    res = await r.async_add_executor_job(
        get_last_statistics,
        hass,
        1,
        statistic_id,
        True,
        set(["last_reset", "max", "mean", "min", "state", "sum"]),
    )
    if not res:
        return None

    return res[statistic_id][0]


class TimeBlocs:
    def __init__(self, stat_type: str):
        fn = {
            "yearly": self.yearly,
            "monthly": self.monthly,
            "weekly": self.weekly,
            "daily": self.daily,
            "hourly": self.hourly,
        }
        self._fn = fn.get(stat_type)

    def yearly(self, state):
        return dt_util.as_local(datetime.fromtimestamp(state["ts"])).replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )

    def monthly(self, state):
        return dt_util.as_local(datetime.fromtimestamp(state["ts"])).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

    def weekly(self, state):
        dttt = dt_util.as_local(datetime.fromtimestamp(state["ts"])).timetuple()

        return dt_util.as_local(datetime.fromtimestamp(state["ts"])).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=dttt.tm_wday)

    def daily(self, state):
        return dt_util.as_local(datetime.fromtimestamp(state["ts"])).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    def hourly(self, state):
        return dt_util.as_local(datetime.fromtimestamp(state["ts"])).replace(
            minute=0, second=0, microsecond=0
        )

    @property
    def fn(self):
        return self._fn
