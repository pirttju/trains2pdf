"""
models.py - Core data classes with multilingual support.

Times are stored as integer minutes after midnight of the *service day*.
Values >= 1440 are legal and mean "after midnight" (GTFS 24:16:00 -> 1456),
so ordering and direction checks stay correct for overnight trains.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Set
from datetime import date


class ServiceType(Enum):
    RESTAURANT = "ravintola"
    BISTRO = "kahvila"
    WHEELCHAIR = "invapaikka"
    SLEEPER = "makuuvaunu"
    CAR_CARRIER = "autovaunu"
    BICYCLE = "polkupyörä"


class TrainClass(Enum):
    CLASS_1_2 = "1 2"
    CLASS_2 = "2"


def format_minutes(m: Optional[int]) -> str:
    """Minutes after service-day midnight -> 'hh.mm' clock time (wraps past 24h)."""
    if m is None:
        return ""
    m %= 1440
    return f"{m // 60:02d}.{m % 60:02d}"


@dataclass
class StopCall:
    station_code: str
    station_name: str
    arrival: Optional[int] = None      # None at the first stop of a trip
    departure: Optional[int] = None    # None at the last stop of a trip
    sequence: int = 0
    is_passing: bool = False

    @property
    def any_time(self) -> Optional[int]:
        return self.departure if self.departure is not None else self.arrival


@dataclass
class TrainTrip:
    trip_id: str
    train_number: str              # e.g., "1"
    train_type: str                # e.g., "S", "IC"
    run_dates: Set[date]           # concrete dates the trip runs inside the book window
    route_type: str = "102"
    train_class: TrainClass = TrainClass.CLASS_1_2
    services: Set[ServiceType] = field(default_factory=set)
    stops: List[StopCall] = field(default_factory=list)   # ordered by stop_sequence

    @property
    def operating_days(self) -> Set[int]:
        """Weekdays (0=Mon..6=Sun) on which the trip runs at least once."""
        return {d.weekday() for d in self.run_dates}

    @property
    def calls(self) -> Dict[str, StopCall]:
        """First call per station code (convenience view; loops keep only the first visit)."""
        out: Dict[str, StopCall] = {}
        for s in self.stops:
            out.setdefault(s.station_code, s)
        return out


@dataclass
class StationRowConfig:
    station_code: str              # e.g. "HKI", "OL", "TPE"
    display_name_override: Optional[str] = None
    km: Optional[int] = None
    is_arrival: bool = False
    is_connection: bool = False    # feeder row: shows a connecting train from this station


@dataclass
class RouteDefinition:
    table_id: str
    title_fi: str
    title_sv: str
    station_rows: List[StationRowConfig]
    # A trip qualifies when it calls, in table direction, at >= 2 distinct stations
    # of this list. Empty list -> every main (non-connection) station counts.
    filter_stations: List[str] = field(default_factory=list)
    # Alternative to filter_stations: several line sections; >= 2 calls in any one of them qualifies.
    filter_groups: List[List[str]] = field(default_factory=list)
    excluded_train_types: Set[str] = field(default_factory=set)
    # GTFS route_type 109 (commuter) trains are left out unless the table opts in; the booklet
    # tables include regional trains (Hanko, Kotka, Lahti-Riihimäki, Nokia...) coded as 109.
    include_commuter: bool = False
    min_transfer_minutes: int = 4
    max_transfer_wait_minutes: int = 60

    def get_title(self, lang: str = "fi") -> str:
        return self.title_sv if lang == "sv" else self.title_fi
