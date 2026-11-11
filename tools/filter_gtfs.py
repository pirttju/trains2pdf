#!/usr/bin/env python3
"""
GTFS Subsetting and Filtering Utility
Filters large GTFS datasets by date range (optional), route types, and stations/bounding box,
preserving complete routes and trips.
"""

import argparse
import csv
import datetime
import io
import sys
import zipfile


def parse_date(date_str: str) -> datetime.date:
    """Parse date from YYYYMMDD or YYYY-MM-DD format."""
    clean = date_str.replace("-", "").strip()
    return datetime.datetime.strptime(clean, "%Y%m%d").date()


def get_cell(row: list, idx: int | None) -> str:
    """Safely retrieve and strip a cell value from a CSV row."""
    if idx is not None and 0 <= idx < len(row):
        return row[idx].strip()
    return ""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Filter GTFS zip archive by date (optional), route type, and station/bbox."
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Path to input GTFS .zip")
    parser.add_argument("--output", "-o", required=True,
                        help="Path to output GTFS .zip")

    # Date range filters (optional)
    parser.add_argument(
        "--start", "-s", help="Start date (YYYY-MM-DD or YYYYMMDD)")
    parser.add_argument(
        "--end", "-e", help="End date (YYYY-MM-DD or YYYYMMDD)")

    # Route type filters
    parser.add_argument(
        "--route-types",
        default="0,1,2,3,4,5,6,7,11,12",
        help="Comma-separated route_type integers.",
    )
    parser.add_argument(
        "--route-rail",
        action="store_true",
        help="Route type 2 (Rail), extended rail types (100-117), and rail replacement bus (714).",
    )

    # Station filters (either bbox or stops file, or both)
    parser.add_argument(
        "--stops-file",
        help="Text file with stop IDs (one per line) to filter by.",
    )
    parser.add_argument(
        "--bbox",
        help="Bounding box: min_lat,min_lon,max_lat,max_lon",
    )

    args = parser.parse_args()

    # Enforce date consistency
    if bool(args.start) != bool(args.end):
        parser.error("Both --start and --end must be provided together.")

    if args.start and args.end:
        start_dt = parse_date(args.start)
        end_dt = parse_date(args.end)
        if start_dt > end_dt:
            parser.error("--start date cannot be after --end date.")

    return args


def get_active_service_ids(
    zip_ref: zipfile.ZipFile, query_start: datetime.date, query_end: datetime.date
) -> set:
    """Determine service_ids that run on at least one day within [query_start, query_end]."""
    print(
        f"[*] Analyzing service validity between {query_start} and {query_end}...")
    calendar_patterns = {}
    weekday_keys = ["monday", "tuesday", "wednesday",
                    "thursday", "friday", "saturday", "sunday"]

    # 1. Parse calendar.txt
    if "calendar.txt" in zip_ref.namelist():
        with zip_ref.open("calendar.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                s_id = (row.get("service_id") or "").strip()
                if not s_id:
                    continue
                s_start = parse_date(row["start_date"])
                s_end = parse_date(row["end_date"])
                weekdays = [int(row[k]) for k in weekday_keys]
                calendar_patterns[s_id] = (s_start, s_end, weekdays)

    # 2. Parse calendar_dates.txt
    exceptions = {}
    if "calendar_dates.txt" in zip_ref.namelist():
        with zip_ref.open("calendar_dates.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                s_id = (row.get("service_id") or "").strip()
                if not s_id:
                    continue
                dt = parse_date(row["date"])
                ex_type = int(row["exception_type"])
                if s_id not in exceptions:
                    exceptions[s_id] = {}
                exceptions[s_id][dt] = ex_type

    # 3. Check which services operate at least 1 day in the target window
    active_services = set()
    all_service_ids = set(calendar_patterns.keys()).union(exceptions.keys())

    day_count = (query_end - query_start).days + 1
    target_dates = [query_start +
                    datetime.timedelta(days=i) for i in range(day_count)]

    for s_id in all_service_ids:
        c_entry = calendar_patterns.get(s_id)
        s_exceptions = exceptions.get(s_id, {})

        is_active = False
        for dt in target_dates:
            if dt in s_exceptions:
                if s_exceptions[dt] == 1:
                    is_active = True
                    break
                elif s_exceptions[dt] == 2:
                    continue

            if c_entry:
                s_start, s_end, weekdays = c_entry
                if s_start <= dt <= s_end and weekdays[dt.weekday()] == 1:
                    is_active = True
                    break

        if is_active:
            active_services.add(s_id)

    print(
        f"    -> Found {len(active_services)} active service_ids in date range.")
    return active_services


def get_matching_routes(zip_ref: zipfile.ZipFile, route_types: set) -> set:
    """Find route_ids matching the target route_types."""
    matching_routes = set()
    if "routes.txt" not in zip_ref.namelist():
        raise FileNotFoundError("routes.txt missing from GTFS archive.")

    with zip_ref.open("routes.txt") as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
        for row in reader:
            try:
                if int(row["route_type"]) in route_types:
                    matching_routes.add(row["route_id"].strip())
            except (ValueError, KeyError, TypeError):
                continue

    print(
        f"[*] Found {len(matching_routes)} routes matching route_types: {route_types}")
    return matching_routes


def get_candidate_stops(
    zip_ref: zipfile.ZipFile, stops_file: str, bbox: tuple
) -> set:
    """
    Find stop_ids matching bbox or stop ID list, expanding bidirectionally
    (children -> parents and parents -> all sibling platforms/children).
    """
    if not stops_file and not bbox:
        return None

    target_stop_ids = set()
    if stops_file:
        try:
            with open(stops_file, "r", encoding="utf-8") as f:
                for line in f:
                    sid = line.strip()
                    if sid:
                        target_stop_ids.add(sid)
            print(
                f"[*] Loaded {len(target_stop_ids)} stop IDs from {stops_file}")
        except FileNotFoundError:
            print(
                f"[!] Warning: Stops file '{stops_file}' not found. Falling back to all stops.")
            return None

    if not target_stop_ids and not bbox:
        print(
            "[*] Stops file is empty and no bbox provided. Falling back to including all stops.")
        return None

    min_lat, min_lon, max_lat, max_lon = bbox if bbox else (
        None, None, None, None)

    parent_to_children = {}
    child_to_parent = {}
    spatially_matched_stops = set()

    with zip_ref.open("stops.txt") as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
        for row in reader:
            sid = (row.get("stop_id") or "").strip()
            pid = (row.get("parent_station") or "").strip()

            if sid and pid:
                child_to_parent[sid] = pid
                parent_to_children.setdefault(pid, set()).add(sid)

            if bbox and sid:
                try:
                    lat = float(row["stop_lat"])
                    lon = float(row["stop_lon"])
                    if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                        spatially_matched_stops.add(sid)
                except (ValueError, KeyError, TypeError):
                    continue

    matched_stops = target_stop_ids.union(spatially_matched_stops)

    if not matched_stops:
        print("[!] Warning: Bounding box / stop criteria matched 0 stops. Falling back to including all stops.")
        return None

    # Bidirectional expansion:
    # 1. Expand upwards: include parent stations of matched platforms
    expanded_stops = set(matched_stops)
    for sid in matched_stops:
        if sid in child_to_parent:
            expanded_stops.add(child_to_parent[sid])

    # 2. Expand downwards: include all sibling platforms for any included parent station
    for sid in list(expanded_stops):
        if sid in parent_to_children:
            expanded_stops.update(parent_to_children[sid])

    print(f"[*] Filter matched {len(expanded_stops)} total stops/platforms.")
    return expanded_stops


def stream_filter_stop_times(
    zip_ref: zipfile.ZipFile,
    candidate_trips: set,
    candidate_stops: set,
) -> set:
    """Pass 1: Identifies trips that call at least once at candidate_stops."""
    print("[*] Pass 1/2: Scanning stop_times.txt to identify served trips...")
    valid_trips = set()

    with zip_ref.open("stop_times.txt") as f:
        text_stream = io.TextIOWrapper(f, encoding="utf-8-sig")
        reader = csv.reader(text_stream)
        header = next(reader, None)
        if not header:
            return valid_trips

        trip_idx = header.index("trip_id")
        stop_idx = header.index("stop_id")

        row_count = 0
        for row in reader:
            if not row:
                continue
            row_count += 1
            trip_id = get_cell(row, trip_idx)
            if trip_id in candidate_trips:
                if get_cell(row, stop_idx) in candidate_stops:
                    valid_trips.add(trip_id)

    print(f"    -> Scanned {row_count:,} stop times rows.")
    print(
        f"    -> Retained {len(valid_trips):,} trips serving target stations.")
    return valid_trips


def main():
    args = parse_args()

    has_date_filter = bool(args.start and args.end)
    if has_date_filter:
        query_start = parse_date(args.start)
        query_end = parse_date(args.end)

    if args.route_rail:
        # Route type 2 (Rail), extended rail types (100 to 117), and rail replacement bus (714)
        route_types = {2, 714} | set(range(100, 118))
    else:
        route_types = {int(rt.strip())
                       for rt in args.route_types.split(",") if rt.strip()}

    bbox = None
    if args.bbox:
        parts = [float(p.strip()) for p in args.bbox.split(",")]
        if len(parts) != 4:
            raise ValueError(
                "Bounding box must be min_lat,min_lon,max_lat,max_lon")
        bbox = tuple(parts)

    with zipfile.ZipFile(args.input, "r") as in_zip, zipfile.ZipFile(
        args.output, "w", compression=zipfile.ZIP_DEFLATED
    ) as out_zip:

        # Step 1: Active Services
        if has_date_filter:
            active_services = get_active_service_ids(
                in_zip, query_start, query_end)
        else:
            print("[*] No date range specified. Retaining services across all dates.")
            active_services = None

        # Step 2: Route Filtering
        target_routes = get_matching_routes(in_zip, route_types)

        # Step 3: Stop Filtering
        target_stops = get_candidate_stops(in_zip, args.stops_file, bbox)

        # Step 4: Candidate Trips
        candidate_trips = set()
        with in_zip.open("trips.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                r_id = (row.get("route_id") or "").strip()
                s_id = (row.get("service_id") or "").strip()
                t_id = (row.get("trip_id") or "").strip()
                if r_id in target_routes:
                    if active_services is None or s_id in active_services:
                        candidate_trips.add(t_id)
        print(f"    -> Candidate trips: {len(candidate_trips)}")

        # Step 5: Stop Times Pass 1
        if target_stops is None:
            print("[*] No stop filter active. Retaining all candidate trips.")
            final_trips = candidate_trips
        else:
            final_trips = stream_filter_stop_times(
                in_zip, candidate_trips, target_stops)

        # Step 6: Stop Times Pass 2
        print("[*] Writing stop_times.txt for matched trips...")
        final_stops_needed = set()
        with in_zip.open("stop_times.txt") as f_in, out_zip.open("stop_times.txt", "w") as f_out:
            text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
            text_out = io.TextIOWrapper(f_out, encoding="utf-8", newline="")
            reader = csv.reader(text_in)
            writer = csv.writer(text_out)

            header = next(reader, None)
            if header:
                writer.writerow(header)
                trip_idx = header.index("trip_id")
                stop_idx = header.index("stop_id")

                for row in reader:
                    if not row:
                        continue
                    if get_cell(row, trip_idx) in final_trips:
                        writer.writerow(row)
                        final_stops_needed.add(get_cell(row, stop_idx))
            text_out.flush()

        # Step 7: Write trips.txt
        print("[*] Writing trips.txt...")
        final_routes_needed = set()
        final_services_needed = set()
        final_shapes_needed = set()

        with in_zip.open("trips.txt") as f_in, out_zip.open("trips.txt", "w") as f_out:
            text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
            text_out = io.TextIOWrapper(f_out, encoding="utf-8", newline="")
            reader = csv.reader(text_in)
            writer = csv.writer(text_out)

            header = next(reader, None)
            if header:
                writer.writerow(header)
                trip_idx = header.index("trip_id")
                route_idx = header.index("route_id")
                service_idx = header.index("service_id")
                shape_idx = header.index(
                    "shape_id") if "shape_id" in header else None

                for row in reader:
                    if not row:
                        continue
                    if get_cell(row, trip_idx) in final_trips:
                        writer.writerow(row)
                        final_routes_needed.add(get_cell(row, route_idx))
                        final_services_needed.add(get_cell(row, service_idx))
                        shape_val = get_cell(row, shape_idx)
                        if shape_val:
                            final_shapes_needed.add(shape_val)
            text_out.flush()

        # Step 8: Write shapes.txt
        if "shapes.txt" in in_zip.namelist() and final_shapes_needed:
            print("[*] Filtering and writing shapes.txt...")
            with in_zip.open("shapes.txt") as f_in, out_zip.open("shapes.txt", "w") as f_out:
                text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
                text_out = io.TextIOWrapper(
                    f_out, encoding="utf-8", newline="")
                reader = csv.reader(text_in)
                writer = csv.writer(text_out)

                header = next(reader, None)
                if header:
                    writer.writerow(header)
                    shape_idx = header.index("shape_id")

                    shape_pts_written = 0
                    for row in reader:
                        if not row:
                            continue
                        if get_cell(row, shape_idx) in final_shapes_needed:
                            writer.writerow(row)
                            shape_pts_written += 1
                    text_out.flush()
                    print(
                        f"    -> Retained {shape_pts_written:,} shape points for {len(final_shapes_needed):,} shapes.")

        # Step 9: Write routes.txt
        print("[*] Writing routes.txt...")
        final_agencies_needed = set()
        with in_zip.open("routes.txt") as f_in, out_zip.open("routes.txt", "w") as f_out:
            text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
            text_out = io.TextIOWrapper(f_out, encoding="utf-8", newline="")
            reader = csv.reader(text_in)
            writer = csv.writer(text_out)

            header = next(reader, None)
            if header:
                writer.writerow(header)
                route_idx = header.index("route_id")
                agency_idx = header.index(
                    "agency_id") if "agency_id" in header else None

                for row in reader:
                    if not row:
                        continue
                    if get_cell(row, route_idx) in final_routes_needed:
                        writer.writerow(row)
                        agency_val = get_cell(row, agency_idx)
                        if agency_val:
                            final_agencies_needed.add(agency_val)
            text_out.flush()

        # Step 10: Write stops.txt (including parent stations recursively)
        print("[*] Writing stops.txt...")
        with in_zip.open("stops.txt") as f_in:
            reader = csv.DictReader(
                io.TextIOWrapper(f_in, encoding="utf-8-sig"))
            parent_stations = {}
            for row in reader:
                s_id = (row.get("stop_id") or "").strip()
                p_id = (row.get("parent_station") or "").strip()
                if s_id and p_id:
                    parent_stations[s_id] = p_id

        # Resolve parent station hierarchy
        added = True
        while added:
            added = False
            for sid in list(final_stops_needed):
                parent = parent_stations.get(sid)
                if parent and parent not in final_stops_needed:
                    final_stops_needed.add(parent)
                    added = True

        with in_zip.open("stops.txt") as f_in, out_zip.open("stops.txt", "w") as f_out:
            text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
            text_out = io.TextIOWrapper(f_out, encoding="utf-8", newline="")
            reader = csv.reader(text_in)
            writer = csv.writer(text_out)

            header = next(reader, None)
            if header:
                # <-- Fixed: writes stops.txt header row
                writer.writerow(header)
                stop_idx = header.index("stop_id")

                for row in reader:
                    if not row:
                        continue
                    if get_cell(row, stop_idx) in final_stops_needed:
                        writer.writerow(row)
            text_out.flush()

        # Step 11: Write agency.txt
        if "agency.txt" in in_zip.namelist():
            print("[*] Writing agency.txt...")
            with in_zip.open("agency.txt") as f_in, out_zip.open("agency.txt", "w") as f_out:
                text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
                text_out = io.TextIOWrapper(
                    f_out, encoding="utf-8", newline="")
                reader = csv.reader(text_in)
                writer = csv.writer(text_out)

                header = next(reader, None)
                if header:
                    writer.writerow(header)
                    agency_idx = header.index(
                        "agency_id") if "agency_id" in header else None

                    for row in reader:
                        if not row:
                            continue
                        if agency_idx is None or not final_agencies_needed or get_cell(row, agency_idx) in final_agencies_needed:
                            writer.writerow(row)
                text_out.flush()

        # Step 12: Write calendar.txt and calendar_dates.txt
        for cal_file in ["calendar.txt", "calendar_dates.txt"]:
            if cal_file in in_zip.namelist():
                print(f"[*] Writing {cal_file}...")
                with in_zip.open(cal_file) as f_in, out_zip.open(cal_file, "w") as f_out:
                    text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
                    text_out = io.TextIOWrapper(
                        f_out, encoding="utf-8", newline="")
                    reader = csv.reader(text_in)
                    writer = csv.writer(text_out)

                    header = next(reader, None)
                    if header:
                        writer.writerow(header)
                        service_idx = header.index("service_id")

                        for row in reader:
                            if not row:
                                continue
                            if get_cell(row, service_idx) in final_services_needed:
                                writer.writerow(row)
                    text_out.flush()

        # Step 13: Write transfers.txt (if present)
        if "transfers.txt" in in_zip.namelist():
            print("[*] Filtering and writing transfers.txt...")
            with in_zip.open("transfers.txt") as f_in, out_zip.open("transfers.txt", "w") as f_out:
                text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
                text_out = io.TextIOWrapper(
                    f_out, encoding="utf-8", newline="")
                reader = csv.reader(text_in)
                writer = csv.writer(text_out)

                header = next(reader, None)
                if header:
                    writer.writerow(header)
                    from_idx = header.index(
                        "from_stop_id") if "from_stop_id" in header else None
                    to_idx = header.index(
                        "to_stop_id") if "to_stop_id" in header else None

                    if from_idx is not None and to_idx is not None:
                        for row in reader:
                            if not row:
                                continue
                            if (get_cell(row, from_idx) in final_stops_needed and
                                    get_cell(row, to_idx) in final_stops_needed):
                                writer.writerow(row)
                text_out.flush()

        # Step 14: Write frequencies.txt (if present)
        if "frequencies.txt" in in_zip.namelist():
            print("[*] Filtering and writing frequencies.txt...")
            with in_zip.open("frequencies.txt") as f_in, out_zip.open("frequencies.txt", "w") as f_out:
                text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
                text_out = io.TextIOWrapper(
                    f_out, encoding="utf-8", newline="")
                reader = csv.reader(text_in)
                writer = csv.writer(text_out)

                header = next(reader, None)
                if header:
                    writer.writerow(header)
                    trip_idx = header.index(
                        "trip_id") if "trip_id" in header else None

                    if trip_idx is not None:
                        for row in reader:
                            if not row:
                                continue
                            if get_cell(row, trip_idx) in final_trips:
                                writer.writerow(row)
                text_out.flush()

        # Step 15: Filter and write attributions.txt
        if "attributions.txt" in in_zip.namelist():
            print("[*] Filtering and writing attributions.txt...")
            with in_zip.open("attributions.txt") as f_in, out_zip.open("attributions.txt", "w") as f_out:
                text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
                text_out = io.TextIOWrapper(
                    f_out, encoding="utf-8", newline="")
                reader = csv.reader(text_in)
                writer = csv.writer(text_out)

                header = next(reader, None)
                if header:
                    writer.writerow(header)
                    trip_idx = header.index(
                        "trip_id") if "trip_id" in header else None
                    route_idx = header.index(
                        "route_id") if "route_id" in header else None
                    agency_idx = header.index(
                        "agency_id") if "agency_id" in header else None

                    kept_count = 0
                    for row in reader:
                        if not row:
                            continue
                        keep = True
                        trip_val = get_cell(row, trip_idx)
                        route_val = get_cell(row, route_idx)
                        agency_val = get_cell(row, agency_idx)

                        if trip_val:
                            keep = trip_val in final_trips
                        elif route_val:
                            keep = route_val in final_routes_needed
                        elif agency_val:
                            keep = agency_val in final_agencies_needed

                        if keep:
                            writer.writerow(row)
                            kept_count += 1
                    text_out.flush()
                    print(
                        f"    -> Retained {kept_count:,} attribution entries.")

        # Step 16: Passthrough remaining meta files
        for extra in ["feed_info.txt"]:
            if extra in in_zip.namelist():
                print(f"[*] Copying {extra}...")
                out_zip.writestr(extra, in_zip.read(extra))

    print(f"[✔] Successfully created filtered GTFS archive at: {args.output}")


if __name__ == "__main__":
    main()
