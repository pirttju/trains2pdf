"""
gtfs_importer.py - Native Digitraffic GTFS parser with translations and platform mapping.
"""
import zipfile
import csv
import io
import re
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
from typing import Dict, List, Set, Optional, Tuple
from models import TrainTrip, StopCall, TrainClass, ServiceType

# "E (HL 8192)" -> type E, number 8192 ; "IC 22" -> type IC, number 22
_SHORT_NAME_PAREN = re.compile(r"^(\S+)\s*\(\s*\S+\s+(\S+)\s*\)$")


def _parse_gtfs_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y%m%d").date()


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def parse_train_name(short_name: str, route_short_name: str = "", fallback_id: str = "") -> Tuple[str, str]:
    """Return (train_type, train_number) from GTFS trip/route short names."""
    for name in (short_name.strip(), route_short_name.strip()):
        if not name:
            continue
        m = _SHORT_NAME_PAREN.match(name)
        if m:
            return m.group(1), m.group(2)
        parts = name.split()
        if len(parts) >= 2:
            return parts[0], parts[-1]
    name = short_name.strip() or route_short_name.strip()
    if name:
        return name, ""
    return "", fallback_id[:8]


class GTFSImporter:
    WEEKDAY_KEYS = ['monday', 'tuesday', 'wednesday',
                    'thursday', 'friday', 'saturday', 'sunday']

    def __init__(self, gtfs_zip_path: str):
        self.zip_path = gtfs_zip_path
        # code -> {'fi': 'Hanko', 'sv': 'Hangö'}
        self.station_names: Dict[str, Dict[str, str]] = {}
        self.feed_validity: Tuple[Optional[date],
                                  Optional[date]] = (None, None)
        self.window: Tuple[Optional[date], Optional[date]] = (
            None, None)  # dates actually compiled
        # code -> (lat, lon)
        self.station_coords: Dict[str, Tuple[float, float]] = {}

    def _read_csv(self, z: zipfile.ZipFile, filename: str):
        if filename not in z.namelist():
            return []
        with z.open(filename) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig'))
            return list(reader)

    @staticmethod
    def parse_time(t_str: Optional[str]) -> Optional[int]:
        """'HH:MM[:SS]' -> minutes after service-day midnight. Hours >= 24 are kept (no wrap)."""
        if not t_str or not t_str.strip():
            return None
        parts = t_str.strip().split(':')
        if len(parts) < 2:
            return None
        try:
            h, m = int(parts[0]), int(parts[1])
        except ValueError:
            return None
        return h * 60 + m

    @staticmethod
    def detect_default_window(calendar_rows: List[dict], feed_start: Optional[date],
                              feed_end: Optional[date]) -> Tuple[date, date]:
        """Default book period: from feed start to the day before the next timetable change.

        The next change is the earliest calendar start_date (more than a week after the start)
        that is at least half as common as the most common later start_date; in Digitraffic
        feeds these are the December / June / August period switches.
        """
        starts = []
        for r in calendar_rows:
            try:
                starts.append(_parse_gtfs_date(r['start_date']))
            except (KeyError, ValueError):
                continue
        w_start = feed_start or (min(starts) if starts else date.today())
        later = Counter(d for d in starts if d > w_start + timedelta(days=7))
        if later:
            # earliest "big" period start: at least half as common as the most common later start
            top = later.most_common(1)[0][1]
            change = min(d for d, n in later.items() if n * 2 >= top)
            w_end = change - timedelta(days=1)
        else:
            w_end = feed_end or (w_start + timedelta(days=180))
        if feed_end and w_end > feed_end:
            w_end = feed_end
        return w_start, w_end

    def load_feed(self, target_date_start: Optional[date] = None,
                  target_date_end: Optional[date] = None, today: Optional[date] = None) -> List[TrainTrip]:
        """Without target_date_start the book starts today (or at the feed start if that is
        later): days already past are not printed, so they cannot cause exception footnotes.
        Without target_date_end it ends the day before the next timetable change."""
        with zipfile.ZipFile(self.zip_path, 'r') as z:
            stops_rows = self._read_csv(z, 'stops.txt')
            translations_rows = self._read_csv(z, 'translations.txt')
            feed_info_rows = self._read_csv(z, 'feed_info.txt')
            routes_rows = {r['route_id']                           : r for r in self._read_csv(z, 'routes.txt')}
            trips_rows = self._read_csv(z, 'trips.txt')
            stop_times_rows = self._read_csv(z, 'stop_times.txt')
            calendar_rows = self._read_csv(z, 'calendar.txt')
            calendar_dates_rows = self._read_csv(z, 'calendar_dates.txt')

        # 1. feed_info.txt validity dates
        if feed_info_rows:
            fi = feed_info_rows[0]
            if fi.get('feed_start_date') and fi.get('feed_end_date'):
                self.feed_validity = (_parse_gtfs_date(fi['feed_start_date']),
                                      _parse_gtfs_date(fi['feed_end_date']))

        # Book window (inclusive)
        # Default end = day before the next timetable change after the chosen start.
        today = today or date.today()
        default_start = self.feed_validity[0] or today
        if today > default_start and (self.feed_validity[1] is None or today <= self.feed_validity[1]):
            default_start = today
        d_start, d_end = self.detect_default_window(calendar_rows, target_date_start or default_start,
                                                    self.feed_validity[1])
        v_start = target_date_start or d_start
        v_end = target_date_end or d_end
        if v_end < v_start:
            raise ValueError(
                f"Invalid date window: start {v_start} is after end {v_end}")
        self.window = (v_start, v_end)

        # 2. Swedish translations (table_name=stops, field_name=stop_name, field_value=<fi name>)
        sv_translations: Dict[str, str] = {}
        for tr in translations_rows:
            if tr.get('table_name') == 'stops' and tr.get('field_name') == 'stop_name' and tr.get('language') == 'sv':
                sv_translations[tr.get('field_value', '')] = tr.get(
                    'translation', '')

        # 3. Stops & platforms: platform stop_id (HKI_0) -> station code (HKI)
        platform_to_station_code: Dict[str, str] = {}
        for s in stops_rows:
            sid = s['stop_id']
            loc_type = (s.get('location_type') or '0').strip()
            parent = (s.get('parent_station') or '').strip()
            name = (s.get('stop_name') or '').strip()
            if loc_type == '1':
                st_code = sid
                self.station_names[st_code] = {
                    'fi': name, 'sv': sv_translations.get(name) or name}
            else:
                st_code = parent if parent else sid.split('_')[0]
                if st_code not in self.station_names and name:
                    self.station_names[st_code] = {
                        'fi': name, 'sv': sv_translations.get(name) or name}
            platform_to_station_code[sid] = st_code
            if loc_type == '1' or st_code not in self.station_coords:
                try:
                    self.station_coords[st_code] = (
                        float(s['stop_lat']), float(s['stop_lon']))
                except (KeyError, TypeError, ValueError):
                    pass

        # 4. Calendar -> concrete run dates inside the window
        run_dates: Dict[str, Set[date]] = {}
        for row in calendar_rows:
            sid = row['service_id']
            weekdays = {i for i, k in enumerate(self.WEEKDAY_KEYS) if (
                row.get(k) or '').strip() == '1'}
            c_start = max(_parse_gtfs_date(row['start_date']), v_start)
            c_end = min(_parse_gtfs_date(row['end_date']), v_end)
            dates = {d for d in _daterange(c_start, c_end) if d.weekday(
            ) in weekdays} if c_start <= c_end else set()
            run_dates[sid] = dates

        for row in calendar_dates_rows:
            sid = row['service_id']
            c_date = _parse_gtfs_date(row['date'])
            ex = (row.get('exception_type') or '').strip()
            dates = run_dates.setdefault(sid, set())
            if not (v_start <= c_date <= v_end):
                continue
            if ex == '1':
                dates.add(c_date)
            elif ex == '2':
                dates.discard(c_date)

        # 5. Stop times grouped by trip, ordered by stop_sequence
        by_trip: Dict[str, List[dict]] = defaultdict(list)
        for st in stop_times_rows:
            by_trip[st['trip_id']].append(st)

        def build_stops(rows: List[dict]) -> List[StopCall]:
            rows = sorted(rows, key=lambda x: int(x.get('stop_sequence') or 0))
            out: List[StopCall] = []
            for i, st in enumerate(rows):
                platform_id = st['stop_id']
                st_code = platform_to_station_code.get(
                    platform_id, platform_id.split('_')[0])
                arr = self.parse_time(st.get('arrival_time'))
                dep = self.parse_time(st.get('departure_time'))
                if arr is None:
                    arr = dep
                if dep is None:
                    dep = arr
                # The origin has no arrival, the terminus has no departure.
                if i == 0:
                    arr = None
                if i == len(rows) - 1:
                    dep = None
                out.append(StopCall(
                    station_code=st_code,
                    station_name=self.station_names.get(
                        st_code, {}).get('fi', st_code),
                    arrival=arr, departure=dep,
                    sequence=int(st.get('stop_sequence') or 0),
                ))
            return out

        # 6. Assemble train trips
        trips_list: List[TrainTrip] = []
        for tr in trips_rows:
            tid = tr['trip_id']
            dates = run_dates.get(tr['service_id'])
            if not dates:
                continue  # does not run inside the window
            rows = by_trip.get(tid)
            if not rows:
                continue

            route_info = routes_rows.get(tr.get('route_id', ''), {})
            # 102=long distance, 109=commuter
            route_type = (route_info.get('route_type') or '102').strip()
            ttype, tnum = parse_train_name(tr.get('trip_short_name', ''),
                                           route_info.get('route_short_name', ''), tid)

            # Services: only what the feed actually states. Digitraffic gives bikes_allowed;
            # wheelchair_accessible is 0 (unknown) everywhere and dining/sleeper cars are not in
            # GTFS, so nothing else is shown.
            services: Set[ServiceType] = set()
            if (tr.get('bikes_allowed') or '').strip() == '1':
                services.add(ServiceType.BICYCLE)
            if (tr.get('wheelchair_accessible') or '').strip() == '1':
                services.add(ServiceType.WHEELCHAIR)
            # every VR night train (PYO) carries sleeping cars
            if ttype == "PYO":
                services.add(ServiceType.SLEEPER)

            trips_list.append(TrainTrip(
                trip_id=tid,
                train_number=tnum,
                train_type=ttype,
                run_dates=set(dates),
                route_type=route_type,
                train_class=TrainClass.CLASS_2 if (
                    ttype == "HDM" or ttype == "H" or ttype == "PYO" or route_type == "109") else TrainClass.CLASS_1_2,
                services=services,
                stops=build_stops(rows),
            ))

        print(
            f"[INFO] Loaded {len(trips_list)} trips running between {v_start:%d.%m.%Y} and {v_end:%d.%m.%Y}.")
        if not trips_list:
            fs, fe = self.feed_validity
            span = f" (feed covers {fs:%d.%m.%Y} – {fe:%d.%m.%Y})" if fs and fe else ""
            print(f"[WARN] No trips run in the selected period{span}.")
        return trips_list
