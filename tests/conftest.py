import csv
import io
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REAL_FEED = os.path.join(ROOT, "gtfs-passenger-stops.zip")


def _csv(rows, header):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


# Synthetic line A - B - C - D running north (lat increases). X lies far off the line,
# F is a branch station feeding into C.
STOPS = {
    "A": ("Aava", 60.0, 25.0),
    "B": ("Beeta", 60.5, 25.0),
    "C": ("Ceeta", 61.0, 25.0),
    "D": ("Delta", 61.5, 25.0),
    "X": ("Äksä", 60.75, 27.5),
    "F": ("Eff", 61.0, 23.0),
}

# trip_id: (short_name, route_type, service_id, [(station, arr, dep), ...])
TRIPS = {
    "T1": ("IC 1", "102", "DAILY", [("A", "", "22:00:00"), ("B", "23:00:00", "23:01:00"),
                                    ("C", "23:50:00", "24:00:00"), ("D", "25:10:00", "")]),
    "T2": ("IC 2", "102", "DAILY", [("D", "", "08:00:00"), ("C", "08:40:00", "08:41:00"),
                                    ("B", "09:20:00", "09:21:00"), ("A", "10:00:00", "")]),
    "T3": ("IC 3", "102", "DAILY", [("D", "", "22:00:00"), ("C", "22:40:00", "22:41:00"),
                                    ("A", "25:30:00", "")]),
    "T4": ("IC 4", "102", "DAILY", [("A", "", "06:00:00"), ("D", "08:00:00", "")]),
    "T5": ("IC 5", "102", "DAILY", [("A", "", "07:00:00"), ("X", "08:00:00", "08:01:00"),
                                    ("D", "09:00:00", "")]),
    "T6": ("R (HL 9001)", "109", "DAILY", [("A", "", "05:00:00"), ("B", "05:20:00", "")]),
    "T7": ("IC 7", "102", "DAILY", [("F", "", "09:00:00"), ("C", "09:40:00", "")]),
    "T8": ("IC 8", "102", "DAILY", [("A", "", "09:00:00"), ("C", "09:45:00", "09:50:00"),
                                    ("D", "10:30:00", "")]),
    "T9": ("IC 9", "102", "WEEKDAYS", [("A", "", "12:00:00"), ("B", "12:30:00", "12:31:00"),
                                       ("D", "13:30:00", "")]),
    "T10a": ("IC 10", "102", "MON_WED", [("A", "", "14:00:00"), ("D", "15:00:00", "")]),
    "T10b": ("IC 10", "102", "THU_FRI", [("A", "", "14:00:00"), ("D", "15:00:00", "")]),
    "T11": ("IC 11", "102", "ONE_DAY", [("A", "", "16:00:00"), ("D", "17:00:00", "")]),
    "T12": ("IC 12", "102", "OLD", [("A", "", "18:00:00"), ("D", "19:00:00", "")]),
    "T13": ("IC 13", "102", "DAILY", [("A", "", "12:00:00"), ("B", "12:30:00", "12:31:00"),
                                      ("A", "13:00:00", "13:01:00"), ("B", "13:30:00", "13:31:00"),
                                      ("C", "14:00:00", "14:01:00"), ("D", "15:00:00", "")]),
    # Starts mid-table early in the morning: must sort before T8 (both serve C)
    "T14": ("IC 14", "102", "DAILY", [("C", "", "04:30:00"), ("D", "05:10:00", "")]),
    # Leaves the table at junction C towards the feeder station F: must not get a feeder time
    "T15": ("IC 15", "102", "DAILY", [("A", "", "09:00:00"), ("C", "09:45:00", "09:50:00"),
                                      ("F", "10:30:00", "")]),
    # Main train departing C after midnight; its feeder runs on the *next* service day
    "T16": ("IC 16", "102", "DAILY", [("A", "", "23:00:00"), ("C", "24:20:00", "24:30:00"),
                                      ("D", "25:10:00", "")]),
    "T17": ("IC 17", "102", "DAILY", [("F", "", "00:00:00"), ("C", "00:10:00", "")]),
    # Originates at B (used with an arrival-only B row)
    "T18": ("IC 18", "102", "DAILY", [("B", "", "15:30:00"), ("D", "16:30:00", "")]),
}

# window 2027-01-04 (Mon) .. 2027-01-31 (Sun)
CALENDAR = [
    ("DAILY", "1111111", "20270104", "20270131"),
    ("WEEKDAYS", "1111100", "20270104", "20270131"),
    ("MON_WED", "1110000", "20270104", "20270131"),
    ("THU_FRI", "0001100", "20270104", "20270131"),
    ("OLD", "1111111", "20260101", "20260131"),
]
CALENDAR_DATES = [
    ("WEEKDAYS", "20270106", "2"),   # cancelled Wednesday
    ("WEEKDAYS", "20270110", "1"),   # extra Sunday
    ("ONE_DAY", "20270115", "1"),    # calendar_dates-only service
]


def build_feed(path):
    stops_rows = []
    for code, (name, lat, lon) in STOPS.items():
        stops_rows.append([code, name, "", lat, lon, "", "1", "", "", ""])
        stops_rows.append([f"{code}_0", name, "", lat, lon, "", "0", code, "", ""])
    routes, trips, stop_times = [], [], []
    for tid, (short, rtype, svc, calls) in TRIPS.items():
        rid = f"R_{tid}"
        routes.append([rid, "10", short, "", "", rtype])
        trips.append([rid, svc, tid, "", "", short, "", "0", "1"])
        for seq, (st, arr, dep) in enumerate(calls, start=1):
            arr = arr or dep
            dep = dep or arr
            stop_times.append([tid, arr, dep, f"{st}_0", seq, "0", "0"])
    files = {
        "agency.txt": _csv([["10", "VR", "https://vr.fi", "Europe/Helsinki", "", "fi"]],
                           ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_phone", "agency_lang"]),
        "feed_info.txt": _csv([["x", "x", "fi", "20270104", "20270131", "1"]],
                              ["feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_start_date",
                               "feed_end_date", "feed_version"]),
        "stops.txt": _csv(stops_rows, ["stop_id", "stop_name", "stop_desc", "stop_lat", "stop_lon", "stop_url",
                                       "location_type", "parent_station", "stop_code", "platform_code"]),
        "routes.txt": _csv(routes, ["route_id", "agency_id", "route_short_name", "route_long_name", "route_desc",
                                    "route_type"]),
        "trips.txt": _csv(trips, ["route_id", "service_id", "trip_id", "trip_headsign", "block_id",
                                  "trip_short_name", "shape_id", "wheelchair_accessible", "bikes_allowed"]),
        "stop_times.txt": _csv(stop_times, ["trip_id", "arrival_time", "departure_time", "stop_id",
                                            "stop_sequence", "pickup_type", "drop_off_type"]),
        "calendar.txt": _csv([[s, *list(d), a, b] for s, d, a, b in CALENDAR],
                             ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
                              "sunday", "start_date", "end_date"]),
        "calendar_dates.txt": _csv(CALENDAR_DATES, ["service_id", "date", "exception_type"]),
        "translations.txt": _csv([["stops", "stop_name", "Aava", "sv", "Ava"]],
                                 ["table_name", "field_name", "field_value", "language", "translation"]),
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return path


@pytest.fixture(scope="session")
def synthetic_feed(tmp_path_factory):
    return build_feed(str(tmp_path_factory.mktemp("feed") / "synthetic.zip"))


@pytest.fixture(scope="session")
def synthetic_loaded(synthetic_feed):
    from gtfs_importer import GTFSImporter
    imp = GTFSImporter(synthetic_feed)
    trips = imp.load_feed()
    return imp, trips


def synthetic_route():
    from models import RouteDefinition, StationRowConfig
    return RouteDefinition(
        table_id="1", title_fi="Aava - Delta", title_sv="Ava - Delta",
        station_rows=[
            StationRowConfig("A", km=0),
            StationRowConfig("B", km=50),
            StationRowConfig("C", km=100, is_arrival=True),
            StationRowConfig("F", km=40, is_connection=True),
            StationRowConfig("C", km=100),
            StationRowConfig("D", km=150, is_arrival=True),
        ],
    )


@pytest.fixture(scope="session")
def real_loaded():
    if not os.path.exists(REAL_FEED):
        pytest.skip("real GTFS feed not present")
    from gtfs_importer import GTFSImporter
    imp = GTFSImporter(REAL_FEED)
    trips = imp.load_feed()
    return imp, trips
