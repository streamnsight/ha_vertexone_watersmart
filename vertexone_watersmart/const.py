from enum import StrEnum
from typing import Final

DOMAIN: Final = "vertexone_watersmart"
NAME: Final = "VertexOne WaterSmart"
CONF_DISTRICT_NAME: Final = "district"


class SENSOR_TYPES(StrEnum):
    CONSUMPTION: Final = "water_consumption"
    LEAK: Final = "water_leak"
    TEMPERATURE: Final = "temperature"
    PRECIPITATIONS: Final = "precipitation"
