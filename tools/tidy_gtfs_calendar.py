#!/usr/bin/env python3
import csv
import io
import os
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DATE_FORMAT = "%Y%m%d"


def parse_date(d_str: str) -> datetime:
    return datetime.strptime(d_str.strip(), DATE_FORMAT)


def format_date(dt: datetime) -> str:
    return dt.strftime(DATE_FORMAT)


def reconstruct_active_dates(calendar_csv_file, calendar_dates_csv_file):
    """
    Reconstructs the full set of operating dates for every service_id
    from calendar.txt and calendar_dates.txt.
    """
    active_dates_by_service = defaultdict(set)
    existing_services = {}

    # 1. Process calendar.txt
    if calendar_csv_file is not None:
        reader = csv.DictReader(calendar_csv_file)
        for row in reader:
            service_id = row["service_id"].strip()
            existing_services[service_id] = row
            start_dt = parse_date(row["start_date"])
            end_dt = parse_date(row["end_date"])
            
            active_weekdays = {i for i, day in enumerate(WEEKDAYS) if row.get(day, "0").strip() == "1"}
            
            cur = start_dt
            while cur <= end_dt:
                if cur.weekday() in active_weekdays:
                    active_dates_by_service[service_id].add(cur)
                cur += timedelta(days=1)

    # 2. Process calendar_dates.txt
    if calendar_dates_csv_file is not None:
        reader = csv.DictReader(calendar_dates_csv_file)
        for row in reader:
            service_id = row["service_id"].strip()
            dt = parse_date(row["date"])
            exception_type = row["exception_type"].strip()

            if exception_type == "1":
                active_dates_by_service[service_id].add(dt)
            elif exception_type == "2":
                active_dates_by_service[service_id].discard(dt)

    return active_dates_by_service, existing_services


def optimize_calendar(active_dates_by_service, existing_services):
    """
    Converts active dates into optimal weekday flags (calendar.txt) 
    and minimized exceptions (calendar_dates.txt).
    """
    new_calendar_rows = []
    new_calendar_dates_rows = []

    for service_id, active_dates in active_dates_by_service.items():
        if not active_dates:
            # Service exists but has 0 active days; keep original date bounds if available
            orig = existing_services.get(service_id, {})
            start_date = orig.get("start_date", "19700101")
            end_date = orig.get("end_date", "19700101")
            cal_row = {day: "0" for day in WEEKDAYS}
            cal_row["service_id"] = service_id
            cal_row["start_date"] = start_date
            cal_row["end_date"] = end_date
            new_calendar_rows.append(cal_row)
            continue

        start_dt = min(active_dates)
        end_dt = max(active_dates)

        # Count total vs. active occurrences for each day of the week
        total_by_weekday = defaultdict(int)
        active_by_weekday = defaultdict(int)
        all_dates_by_weekday = defaultdict(list)

        cur = start_dt
        while cur <= end_dt:
            w = cur.weekday()
            total_by_weekday[w] += 1
            all_dates_by_weekday[w].append(cur)
            if cur in active_dates:
                active_by_weekday[w] += 1
            cur += timedelta(days=1)

        cal_row = {
            "service_id": service_id,
            "start_date": format_date(start_dt),
            "end_date": format_date(end_dt),
        }

        # Optimize weekday flags and exceptions
        for w, day_name in enumerate(WEEKDAYS):
            total_count = total_by_weekday[w]
            active_count = active_by_weekday[w]

            # If service runs on > 50% of the occurrences, flag=1 minimizes exceptions
            if total_count > 0 and active_count > (total_count / 2):
                cal_row[day_name] = "1"
                # Add exception_type=2 for dates it does NOT run
                for dt in all_dates_by_weekday[w]:
                    if dt not in active_dates:
                        new_calendar_dates_rows.append({
                            "service_id": service_id,
                            "date": format_date(dt),
                            "exception_type": "2"
                        })
            else:
                cal_row[day_name] = "0"
                # Add exception_type=1 for dates it DOES run
                for dt in all_dates_by_weekday[w]:
                    if dt in active_dates:
                        new_calendar_dates_rows.append({
                            "service_id": service_id,
                            "date": format_date(dt),
                            "exception_type": "1"
                        })

        new_calendar_rows.append(cal_row)

    # Sort outputs deterministically
    new_calendar_rows.sort(key=lambda r: r["service_id"])
    new_calendar_dates_rows.sort(key=lambda r: (r["service_id"], r["date"]))

    return new_calendar_rows, new_calendar_dates_rows


def process_gtfs(input_path: str, output_path: str):
    """
    Tidies GTFS calendar files from a directory or .zip archive.
    """
    in_p = Path(input_path)
    out_p = Path(output_path)

    if in_p.is_file() and in_p.suffix.lower() == ".zip":
        with zipfile.ZipFile(in_p, "r") as zin:
            cal_file = io.TextIOWrapper(zin.open("calendar.txt"), "utf-8-sig") if "calendar.txt" in zin.namelist() else None
            cal_dates_file = io.TextIOWrapper(zin.open("calendar_dates.txt"), "utf-8-sig") if "calendar_dates.txt" in zin.namelist() else None

            active_dates, existing_services = reconstruct_active_dates(cal_file, cal_dates_file)
            new_cal, new_cal_dates = optimize_calendar(active_dates, existing_services)

            # Write output zip preserving other GTFS files
            with zipfile.ZipFile(out_p, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    if item.filename not in ["calendar.txt", "calendar_dates.txt"]:
                        zout.writestr(item, zin.read(item.filename))

                # Write optimized calendar.txt
                cal_buf = io.StringIO()
                cal_fieldnames = ["service_id"] + WEEKDAYS + ["start_date", "end_date"]
                writer = csv.DictWriter(cal_buf, fieldnames=cal_fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(new_cal)
                zout.writestr("calendar.txt", cal_buf.getvalue())

                # Write optimized calendar_dates.txt (if there are exceptions)
                if new_cal_dates:
                    dates_buf = io.StringIO()
                    writer = csv.DictWriter(dates_buf, fieldnames=["service_id", "date", "exception_type"], lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(new_cal_dates)
                    zout.writestr("calendar_dates.txt", dates_buf.getvalue())

    elif in_p.is_dir():
        out_p.mkdir(parents=True, exist_ok=True)

        cal_path = in_p / "calendar.txt"
        dates_path = in_p / "calendar_dates.txt"

        cal_file = open(cal_path, "r", encoding="utf-8-sig") if cal_path.exists() else None
        dates_file = open(dates_path, "r", encoding="utf-8-sig") if dates_path.exists() else None

        active_dates, existing_services = reconstruct_active_dates(cal_file, dates_file)
        if cal_file: cal_file.close()
        if dates_file: dates_file.close()

        new_cal, new_cal_dates = optimize_calendar(active_dates, existing_services)

        # Copy over all other GTFS files
        for f in in_p.glob("*.txt"):
            if f.name not in ["calendar.txt", "calendar_dates.txt"]:
                shutil.copy(f, out_p / f.name)

        # Write new calendar.txt
        with open(out_p / "calendar.txt", "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["service_id"] + WEEKDAYS + ["start_date", "end_date"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(new_cal)

        # Write new calendar_dates.txt
        if new_cal_dates:
            with open(out_p / "calendar_dates.txt", "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["service_id", "date", "exception_type"], lineterminator="\n")
                writer.writeheader()
                writer.writerows(new_cal_dates)
        elif (out_p / "calendar_dates.txt").exists():
            (out_p / "calendar_dates.txt").unlink()

    print(f"Successfully processed GTFS dataset and saved to: {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Tidy and optimize GTFS calendar definitions.")
    parser.add_argument("--input", "-i", required=True, help="Path to input GTFS .zip")
    parser.add_argument("--output", "-o", required=True, help="Path to output GTFS .zip")
    args = parser.parse_args()
    
    process_gtfs(args.input, args.output)