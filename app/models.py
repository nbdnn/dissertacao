from dataclasses import dataclass
from typing import Optional


@dataclass
class Satellite:
    norad_cat_id: int
    name: str
    object_type: str = "UNKNOWN"
    # Dimensions for collision probability (optional defaults)
    rcs_size: Optional[str] = None


@dataclass
class TLEData:
    satellite: Satellite
    tle_line1: str
    tle_line2: str
    epoch: str  # As string for now, or datetime

    @property
    def object_name(self):
        return self.satellite.name

    @property
    def norad_cat_id(self):
        return self.satellite.norad_cat_id
