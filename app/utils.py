from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from org.orekit.time import AbsoluteDate  # type: ignore


def orekit_date_to_datetime(orekit_date: 'AbsoluteDate') -> datetime:
    """Converte AbsoluteDate do Orekit para datetime Python (UTC)."""
    from org.orekit.time import TimeScalesFactory  # type: ignore
    utc = TimeScalesFactory.getUTC()
    java_date = orekit_date.toDate(utc)
    return datetime.fromtimestamp(java_date.getTime() / 1000.0, timezone.utc)


def get_orbital_elements(tle_obj):
    """
    Retorna (perigeo_km, apogeo_km) aproximados usando Orekit TLE.
    """
    from org.orekit.utils import Constants  # type: ignore

    mu = Constants.WGS84_EARTH_MU

    n = tle_obj.getMeanMotion()
    e = tle_obj.getE()

    # Semi-major axis a = (mu / n^2)^(1/3)
    a = (mu / (n * n)) ** (1.0 / 3.0)

    # Earth Radius (avg)
    re = Constants.WGS84_EARTH_EQUATORIAL_RADIUS

    perigee_km = (a * (1.0 - e) - re) / 1000.0
    apogee_km = (a * (1.0 + e) - re) / 1000.0

    return perigee_km, apogee_km
