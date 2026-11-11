#!/usr/bin/env python3
"""
GTFS Merge Utility with Stop Unification & Timezone Offset Adjustment
Merges two large GTFS datasets into a single GTFS archive with collision avoidance,
custom stop/station unification, and per-station time adjustments.
"""

import argparse
import csv
import io
import sys
import zipfile

# Definitions of columns representing identifiers
ID_COLUMNS = {
    "agency.txt": {"agency_id"},
    "routes.txt": {"route_id", "agency_id"},
    "trips.txt": {"trip_id", "route_id", "service_id", "shape_id", "block_id"},
    "stop_times.txt": {"trip_id", "stop_id"},
    "stops.txt": {"stop_id", "parent_station", "level_id"},
    "calendar.txt": {"service_id"},
    "calendar_dates.txt": {"service_id"},
    "shapes.txt": {"shape_id"},
    "transfers.txt": {
        "from_stop_id", "to_stop_id", "from_route_id", "to_route_id",
        "from_trip_id", "to_trip_id"
    },
    "frequencies.txt": {"trip_id"},
    "pathways.txt": {"pathway_id", "from_stop_id", "to_stop_id"},
    "levels.txt": {"level_id"},
    "fare_attributes.txt": {"fare_id", "agency_id"},
    "fare_rules.txt": {"fare_id", "route_id", "origin_id", "destination_id", "contains_id"},
    "attributions.txt": {"attribution_id", "agency_id", "route_id", "trip_id"},
}

# Stop-specific ID columns that must check the merge-stop map
STOP_ID_COLUMNS = {"stop_id", "parent_station", "from_stop_id", "to_stop_id"}


def clean_prefix(val: str) -> str:
    """Sanitize prefix value, allowing omission via '', 'none', 'false', etc."""
    if not val or val.strip().lower() in ("none", "null", "false", '""', "''"):
        return ""
    return val


def parse_time_offset(val: str) -> int:
    """
    Parses time offset into seconds.
    Supports hours as int/float (e.g. '-1', '1.5') or HH:MM / HH:MM:SS (e.g. '-01:00').
    """
    if not val or not val.strip():
        return 0
    val = val.strip()
    sign = -1 if val.startswith("-") else 1
    clean_val = val.lstrip("+-")

    if ":" in clean_val:
        parts = clean_val.split(":")
        if len(parts) == 2:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60
        elif len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            seconds = 0
        return sign * seconds
    else:
        try:
            return sign * int(float(clean_val) * 3600)
        except ValueError:
            return 0


def adjust_gtfs_time(time_str: str, offset_seconds: int) -> str:
    """Applies seconds offset to HH:MM:SS string, preserving GTFS >24h logic."""
    if not time_str or not time_str.strip() or offset_seconds == 0:
        return time_str
    try:
        parts = time_str.strip().split(":")
        if len(parts) != 3:
            return time_str
        total_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        new_sec = total_sec + offset_seconds
        if new_sec < 0:
            # Wrap around 24 hours if negative
            new_sec = (new_sec % 86400 + 86400) % 86400
        h = new_sec // 3600
        m = (new_sec % 3600) // 60
        s = new_sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    except Exception:
        return time_str


def parse_args():
    parser = argparse.ArgumentParser(
        description="Merge two GTFS zip archives with collision avoidance, stop merging, and time offsets."
    )
    parser.add_argument("--input-a", "-a", required=True, help="Path to first GTFS .zip")
    parser.add_argument("--input-b", "-b", required=True, help="Path to second GTFS .zip")
    parser.add_argument("--output", "-o", required=True, help="Path to output merged GTFS .zip")

    # Prefix configuration
    parser.add_argument(
        "--prefix-a",
        default="A_",
        help="Prefix to prepend to identifiers in dataset A. Use '' or 'none' to omit. (Default: 'A_')",
    )
    parser.add_argument(
        "--prefix-b",
        default="B_",
        help="Prefix to prepend to identifiers in dataset B. Use '' or 'none' to omit. (Default: 'B_')",
    )
    parser.add_argument(
        "--no-prefix-a",
        action="store_true",
        help="Explicitly omit prefix for dataset A (equivalent to --prefix-a '')",
    )
    parser.add_argument(
        "--no-prefix-b",
        action="store_true",
        help="Explicitly omit prefix for dataset B (equivalent to --prefix-b '')",
    )

    # Stop merge mapping file
    parser.add_argument(
        "--merge-stops",
        help="CSV file with columns: input,stop_id,output_stop_id,[output_stop_name],[time_offset]",
    )

    return parser.parse_args()


def load_stop_mappings(mapping_file: str):
    """
    Parses stop mapping CSV.
    Returns:
      stop_mappings: {('a', 'stop_id'): (output_stop_id, output_stop_name)}
      time_offsets:  {('a', 'stop_id'): offset_seconds}
    """
    if not mapping_file:
        return {}, {}

    stop_mappings = {}
    time_offsets = {}

    with open(mapping_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = row.get("input", "").strip().lower()
            sid = row.get("stop_id", "").strip()
            out_sid = row.get("output_stop_id", "").strip()
            out_name = row.get("output_stop_name", "").strip() or None

            raw_offset = row.get("time_offset") or row.get("time_offset_hours") or ""
            offset_sec = parse_time_offset(raw_offset)

            if not sid or not out_sid:
                continue

            targets = []
            if src in ["a", "1", "input_a"]:
                targets.append("a")
            elif src in ["b", "2", "input_b"]:
                targets.append("b")
            elif src in ["*", "all", "both", ""]:
                targets.extend(["a", "b"])

            for t in targets:
                stop_mappings[(t, sid)] = (out_sid, out_name)
                if offset_sec != 0:
                    time_offsets[(t, sid)] = offset_sec

    print(f"[*] Loaded {len(stop_mappings)} stop merge rule(s).")
    if time_offsets:
        print(f"[*] Configured {len(time_offsets)} time offset adjustment(s).")
        for (src, sid), offset in time_offsets.items():
            print(f"    -> [{src.upper()}] Stop {sid}: {offset:+d} seconds ({offset/3600:+.2f} hours)")
    return stop_mappings, time_offsets


def get_child_to_parent_map(zip_ref: zipfile.ZipFile) -> dict:
    """Pre-scans stops.txt to link child platforms to parent stations."""
    child_to_parent = {}
    if "stops.txt" in zip_ref.namelist():
        with zip_ref.open("stops.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                sid = row.get("stop_id", "").strip()
                pid = row.get("parent_station", "").strip()
                if sid and pid:
                    child_to_parent[sid] = pid
    return child_to_parent


def map_stop_id(source_tag: str, stop_id: str, prefix: str, stop_mappings: dict) -> str:
    """Resolves stop_id using the merge map; falls back to prefixing."""
    if not stop_id:
        return ""
    key = (source_tag, stop_id)
    if key in stop_mappings:
        return stop_mappings[key][0]
    return (prefix + stop_id) if prefix else stop_id


def get_csv_header(zip_ref: zipfile.ZipFile, filename: str) -> list:
    """Reads only the first line of a CSV in a zip file to retrieve its header."""
    with zip_ref.open(filename) as f:
        text_stream = io.TextIOWrapper(f, encoding="utf-8-sig")
        reader = csv.reader(text_stream)
        for row in reader:
            return [col.strip() for col in row]
    return []


def build_column_mapping(source_header: list, union_header: list, filename: str):
    id_fields = ID_COLUMNS.get(filename, set())
    mapping = []
    for src_idx, col_name in enumerate(source_header):
        target_idx = union_header.index(col_name)
        is_id = col_name in id_fields
        is_stop_id = col_name in STOP_ID_COLUMNS
        mapping.append((target_idx, src_idx, is_id, is_stop_id, col_name))
    return mapping


def stream_merge_file(
    filename: str,
    zip_a: zipfile.ZipFile,
    zip_b: zipfile.ZipFile,
    out_zip: zipfile.ZipFile,
    prefix_a: str,
    prefix_b: str,
    stop_mappings: dict,
    time_offsets: dict,
    child_parents_a: dict,
    child_parents_b: dict,
):
    has_a = filename in zip_a.namelist()
    has_b = filename in zip_b.namelist()

    if not has_a and not has_b:
        return

    header_a = get_csv_header(zip_a, filename) if has_a else []
    header_b = get_csv_header(zip_b, filename) if has_b else []

    union_header = list(header_a)
    for col in header_b:
        if col not in union_header:
            union_header.append(col)

    if filename in ["agency.txt", "routes.txt"] and "agency_id" not in union_header:
        union_header.append("agency_id")

    print(f"[*] Processing {filename}...")

    emitted_stop_ids = set()

    with out_zip.open(filename, "w") as f_out:
        text_out = io.TextIOWrapper(f_out, encoding="utf-8", newline="")
        writer = csv.writer(text_out)
        writer.writerow(union_header)

        def write_source(source_zip, source_header, prefix, source_tag, default_agency_id, child_to_parent):
            mapping = build_column_mapping(source_header, union_header, filename)
            union_len = len(union_header)

            stop_id_target_idx = union_header.index("stop_id") if "stop_id" in union_header else None
            stop_name_target_idx = union_header.index("stop_name") if "stop_name" in union_header else None
            agency_id_target_idx = union_header.index("agency_id") if "agency_id" in union_header else None

            from_stop_target_idx = union_header.index("from_stop_id") if "from_stop_id" in union_header else None
            to_stop_target_idx = union_header.index("to_stop_id") if "to_stop_id" in union_header else None

            arr_target_idx = union_header.index("arrival_time") if "arrival_time" in union_header else None
            dep_target_idx = union_header.index("departure_time") if "departure_time" in union_header else None

            with source_zip.open(filename) as f_in:
                text_in = io.TextIOWrapper(f_in, encoding="utf-8-sig")
                reader = csv.reader(text_in)
                next(reader)  # Skip source header

                for row in reader:
                    out_row = [""] * union_len
                    orig_stop_id = None

                    for target_idx, src_idx, is_id, is_stop_id, col_name in mapping:
                        if src_idx < len(row):
                            val = row[src_idx].strip()

                            if is_stop_id and val:
                                if col_name == "stop_id":
                                    orig_stop_id = val
                                val = map_stop_id(source_tag, val, prefix, stop_mappings)
                            elif is_id and val:
                                val = (prefix + val) if prefix else val

                            out_row[target_idx] = val

                    # 1. stops.txt: renaming and deduplication across/within datasets
                    if filename == "stops.txt" and stop_id_target_idx is not None:
                        final_stop_id = out_row[stop_id_target_idx]
                        if final_stop_id in emitted_stop_ids:
                            continue

                        key = (source_tag, orig_stop_id)
                        if key in stop_mappings and stop_name_target_idx is not None:
                            new_name = stop_mappings[key][1]
                            if new_name:
                                out_row[stop_name_target_idx] = new_name

                        emitted_stop_ids.add(final_stop_id)

                    # 2. stop_times.txt: apply time offsets
                    elif filename == "stop_times.txt" and orig_stop_id is not None:
                        parent_id = child_to_parent.get(orig_stop_id)
                        offset = time_offsets.get((source_tag, orig_stop_id), 0)
                        if offset == 0 and parent_id:
                            offset = time_offsets.get((source_tag, parent_id), 0)

                        if offset != 0:
                            if arr_target_idx is not None:
                                out_row[arr_target_idx] = adjust_gtfs_time(out_row[arr_target_idx], offset)
                            if dep_target_idx is not None:
                                out_row[dep_target_idx] = adjust_gtfs_time(out_row[dep_target_idx], offset)

                    # 3. transfers.txt: drop self-transfers resulting from merged stops
                    elif filename == "transfers.txt" and from_stop_target_idx is not None and to_stop_target_idx is not None:
                        if out_row[from_stop_target_idx] and out_row[from_stop_target_idx] == out_row[to_stop_target_idx]:
                            continue

                    # 4. agency.txt / routes.txt safeguard: assign distinct agency if omitted
                    if filename in ["agency.txt", "routes.txt"] and agency_id_target_idx is not None:
                        if not out_row[agency_id_target_idx]:
                            out_row[agency_id_target_idx] = default_agency_id

                    writer.writerow(out_row)

        if has_a:
            def_agency_a = f"{prefix_a}agency" if prefix_a else "agency_a"
            write_source(zip_a, header_a, prefix_a, "a", def_agency_a, child_parents_a)

        if has_b:
            def_agency_b = f"{prefix_b}agency" if prefix_b else "agency_b"
            write_source(zip_b, header_b, prefix_b, "b", def_agency_b, child_parents_b)

        text_out.flush()


def main():
    args = parse_args()

    prefix_a = "" if args.no_prefix_a else clean_prefix(args.prefix_a)
    prefix_b = "" if args.no_prefix_b else clean_prefix(args.prefix_b)

    print(f"[*] Prefix Dataset A: '{prefix_a}' (Empty/Omitted: {prefix_a == ''})")
    print(f"[*] Prefix Dataset B: '{prefix_b}' (Empty/Omitted: {prefix_b == ''})")

    stop_mappings, time_offsets = load_stop_mappings(args.merge_stops)

    with zipfile.ZipFile(args.input_a, "r") as zip_a, \
         zipfile.ZipFile(args.input_b, "r") as zip_b, \
         zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as out_zip:

        # Pre-scan child-parent relationships so platforms inherit parent time offsets
        child_parents_a = get_child_to_parent_map(zip_a)
        child_parents_b = get_child_to_parent_map(zip_b)

        all_files = set(
            f for f in zip_a.namelist() if f.endswith(".txt") and not f.startswith("__MACOSX")
        ).union(
            f for f in zip_b.namelist() if f.endswith(".txt") and not f.startswith("__MACOSX")
        )

        file_order = [
            "agency.txt",
            "stops.txt",
            "routes.txt",
            "calendar.txt",
            "calendar_dates.txt",
            "shapes.txt",
            "trips.txt",
            "stop_times.txt",
            "frequencies.txt",
            "transfers.txt",
            "attributions.txt",
            "feed_info.txt",
        ]

        ordered_files = [f for f in file_order if f in all_files]
        ordered_files += [f for f in all_files if f not in ordered_files]

        for filename in ordered_files:
            stream_merge_file(
                filename,
                zip_a,
                zip_b,
                out_zip,
                prefix_a,
                prefix_b,
                stop_mappings,
                time_offsets,
                child_parents_a,
                child_parents_b,
            )

    print(f"\n[✔] Merged archive successfully written to: {args.output}")


if __name__ == "__main__":
    main()