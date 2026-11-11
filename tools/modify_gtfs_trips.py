import argparse
from collections import defaultdict
import csv
from datetime import datetime, timedelta
import os
import shutil
import tempfile
import zipfile

DAYS_OF_WEEK = [
    'monday',
    'tuesday',
    'wednesday',
    'thursday',
    'friday',
    'saturday',
    'sunday',
]


def parse_date(date_str):
    return datetime.strptime(date_str, '%Y%m%d').date()


def format_date(date_obj):
    return date_obj.strftime('%Y%m%d')


def get_dates_in_range(start_str, end_str):
    start = parse_date(start_str)
    end = parse_date(end_str)
    curr = start
    while curr <= end:
        yield curr
        curr += timedelta(days=1)


def load_rules(rules_csv_path):
    """Loads rules and groups them by trip_short_name."""
    rules_by_trip = defaultdict(list)
    with open(rules_csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            orig_name = row['trip_short_name'].strip()
            new_name = row['new_trip_short_name'].strip()
            date_str = row.get('date', '').strip()
            exc_type = row.get('exception_type', '').strip()

            if date_str:
                rules_by_trip[orig_name].append({
                    'type': 'date',
                    'new_name': new_name,
                    'date': date_str,
                    'exception_type': int(exc_type) if exc_type else 1,
                })
            else:
                weekdays = {
                    i
                    for i, day in enumerate(DAYS_OF_WEEK)
                    if row.get(day, '').strip() == '1'
                }
                rules_by_trip[orig_name].append({
                    'type': 'dow',
                    'new_name': new_name,
                    'weekdays': weekdays,
                })
    return rules_by_trip


def load_gtfs_services(extract_dir):
    """Computes the exact set of active YYYYMMDD dates for every service_id."""
    service_dates = defaultdict(set)
    cal_path = os.path.join(extract_dir, 'calendar.txt')
    cal_dates_path = os.path.join(extract_dir, 'calendar_dates.txt')

    if os.path.exists(cal_path):
        with open(cal_path, mode='r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                sid = row['service_id']
                active_weekdays = {
                    i for i, day in enumerate(DAYS_OF_WEEK) if row[day] == '1'
                }
                for dt in get_dates_in_range(
                    row['start_date'], row['end_date']
                ):
                    if dt.weekday() in active_weekdays:
                        service_dates[sid].add(format_date(dt))

    if os.path.exists(cal_dates_path):
        with open(cal_dates_path, mode='r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                sid = row['service_id']
                dt_str = row['date']
                if row['exception_type'] == '1':
                    service_dates[sid].add(dt_str)
                elif row['exception_type'] == '2':
                    service_dates[sid].discard(dt_str)

    return service_dates


def evaluate_trip_dates(active_dates, rules):
    """Maps each active date of a trip to its target new_trip_short_name (if matched).

    Evaluates 'dow' rules first, then 'date' exception rules so exceptions can
    override.
    """
    date_to_new_name = {}

    # 1. Apply Day-of-Week rules
    for rule in rules:
        if rule['type'] == 'dow':
            for dt_str in active_dates:
                dt = parse_date(dt_str)
                if dt.weekday() in rule['weekdays']:
                    date_to_new_name[dt_str] = rule['new_name']

    # 2. Apply Date Exception rules
    for rule in rules:
        if rule['type'] == 'date':
            dt_str = rule['date']
            if dt_str in active_dates:
                if rule['exception_type'] == 1:
                    date_to_new_name[dt_str] = rule['new_name']
                elif rule['exception_type'] == 2:
                    # If exception_type is 2, remove the modification on this date
                    date_to_new_name.pop(dt_str, None)

    # Group dates by the target new_trip_short_name
    new_name_dates = defaultdict(set)
    for dt_str, new_name in date_to_new_name.items():
        new_name_dates[new_name].add(dt_str)

    unmatched_dates = active_dates - set(date_to_new_name.keys())
    return unmatched_dates, new_name_dates


def duplicate_trip_references(extract_dir, filename, trip_clones):
    """Duplicates rows in stop_times.txt / frequencies.txt for newly created trips."""
    filepath = os.path.join(extract_dir, filename)
    if not os.path.exists(filepath) or not trip_clones:
        return

    temp_path = filepath + '.tmp'
    with (
        open(filepath, mode='r', encoding='utf-8-sig') as infile,
        open(temp_path, mode='w', encoding='utf-8', newline='') as outfile,
    ):
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()

        for row in reader:
            writer.writerow(row)
            tid = row['trip_id']
            if tid in trip_clones:
                for new_tid in trip_clones[tid]:
                    new_row = dict(row)
                    new_row['trip_id'] = new_tid
                    writer.writerow(new_row)

    shutil.move(temp_path, filepath)


def process_gtfs(input_zip, rules_csv, output_zip):
    rules_by_trip = load_rules(rules_csv)

    with tempfile.TemporaryDirectory() as extract_dir:
        # 1. Extract GTFS zip
        with zipfile.ZipFile(input_zip, 'r') as zf:
            zf.extractall(extract_dir)

        service_dates = load_gtfs_services(extract_dir)
        existing_service_ids = set(service_dates.keys())

        trips_path = os.path.join(extract_dir, 'trips.txt')
        with open(trips_path, mode='r', encoding='utf-8-sig') as f:
            trips_reader = csv.DictReader(f)
            trip_fieldnames = trips_reader.fieldnames
            all_trips = list(trips_reader)

        existing_trip_ids = {row['trip_id'] for row in all_trips}

        # Deduplication registry for newly created services (frozenset of dates -> service_id)
        custom_services = {}
        new_calendar_dates_rows = []
        new_calendar_rows = []

        def get_or_create_service(dates_set, base_service_id):
            frozen_dates = frozenset(dates_set)
            if frozen_dates in custom_services:
                return custom_services[frozen_dates]

            idx = 1
            while f'{base_service_id}_mod_{idx}' in existing_service_ids:
                idx += 1
            new_sid = f'{base_service_id}_mod_{idx}'
            existing_service_ids.add(new_sid)
            custom_services[frozen_dates] = new_sid

            # Add dummy row to calendar.txt (all 0s) for strict GTFS validators,
            # and explicit dates to calendar_dates.txt
            min_dt, max_dt = min(dates_set), max(dates_set)
            new_calendar_rows.append({
                'service_id': new_sid,
                'monday': '0',
                'tuesday': '0',
                'wednesday': '0',
                'thursday': '0',
                'friday': '0',
                'saturday': '0',
                'sunday': '0',
                'start_date': min_dt,
                'end_date': max_dt,
            })
            for dt_str in sorted(dates_set):
                new_calendar_dates_rows.append({
                    'service_id': new_sid,
                    'date': dt_str,
                    'exception_type': '1',
                })
            return new_sid

        updated_trips = []
        trip_clones = defaultdict(list)  # orig_trip_id -> [new_trip_ids]

        # 2. Process Trips
        for row in all_trips:
            t_short_name = row.get('trip_short_name', '').strip()
            if t_short_name not in rules_by_trip:
                updated_trips.append(row)
                continue

            sid = row['service_id']
            active_dates = service_dates.get(sid, set())
            if not active_dates:
                updated_trips.append(row)
                continue

            unmatched_dates, new_name_dates = evaluate_trip_dates(
                active_dates, rules_by_trip[t_short_name]
            )

            # Case A: No active dates matched the rules
            if not new_name_dates:
                updated_trips.append(row)
                continue

            # Case B: 100% of active dates matched a single new_trip_short_name (No split needed!)
            if not unmatched_dates and len(new_name_dates) == 1:
                only_new_name = next(iter(new_name_dates.keys()))
                row['trip_short_name'] = only_new_name
                updated_trips.append(row)
                continue

            # Case C: Partial match (Split required)
            # 1. Handle remaining original dates
            if unmatched_dates:
                orig_row = dict(row)
                orig_row['service_id'] = get_or_create_service(
                    unmatched_dates, sid
                )
                updated_trips.append(orig_row)

            # 2. Handle matched dates (can be multiple if different rules map to different names)
            used_original_trip_id = bool(unmatched_dates)
            for new_name, matched_dts in new_name_dates.items():
                new_sid = get_or_create_service(matched_dts, sid)
                new_row = dict(row)
                new_row['service_id'] = new_sid
                new_row['trip_short_name'] = new_name

                if not used_original_trip_id:
                    # Reuse the original trip_id if all original dates were consumed by rules
                    updated_trips.append(new_row)
                    used_original_trip_id = True
                else:
                    # Generate a new trip_id and mark it for stop_times duplication
                    idx = 1
                    orig_tid = row['trip_id']
                    while f'{orig_tid}_mod_{idx}' in existing_trip_ids:
                        idx += 1
                    new_tid = f'{orig_tid}_mod_{idx}'
                    existing_trip_ids.add(new_tid)

                    new_row['trip_id'] = new_tid
                    updated_trips.append(new_row)
                    trip_clones[orig_tid].append(new_tid)

        # 3. Write updated trips.txt
        with open(trips_path, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=trip_fieldnames)
            writer.writeheader()
            writer.writerows(updated_trips)

        # 4. Update calendar.txt and calendar_dates.txt with new split services
        cal_path = os.path.join(extract_dir, 'calendar.txt')
        if os.path.exists(cal_path) and new_calendar_rows:
            with open(cal_path, mode='r', encoding='utf-8-sig') as f:
                cal_fields = csv.DictReader(f).fieldnames
            with open(cal_path, mode='a', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=cal_fields)
                for r in new_calendar_rows:
                    writer.writerow({k: r.get(k, '') for k in cal_fields})

        cal_dates_path = os.path.join(extract_dir, 'calendar_dates.txt')
        if new_calendar_dates_rows:
            file_exists = os.path.exists(cal_dates_path)
            cal_dates_fields = ['service_id', 'date', 'exception_type']
            if file_exists:
                with open(cal_dates_path, mode='r', encoding='utf-8-sig') as f:
                    cal_dates_fields = csv.DictReader(f).fieldnames

            with open(
                cal_dates_path, mode='a', encoding='utf-8', newline=''
            ) as f:
                writer = csv.DictWriter(f, fieldnames=cal_dates_fields)
                if not file_exists:
                    writer.writeheader()
                for r in new_calendar_dates_rows:
                    writer.writerow({k: r.get(k, '') for k in cal_dates_fields})

        # 5. Duplicate stop_times.txt and frequencies.txt for cloned trips
        duplicate_trip_references(extract_dir, 'stop_times.txt', trip_clones)
        duplicate_trip_references(extract_dir, 'frequencies.txt', trip_clones)

        # 6. Repackage into output ZIP
        with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(extract_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, extract_dir)
                    zf.write(full_path, rel_path)

    print(f'Successfully processed GTFS. Output saved to: {output_zip}')
    print(f'New services created: {len(custom_services)}')
    print(
        f'New trips cloned: {sum(len(v) for v in trip_clones.values())}'
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Modify GTFS trip_short_name based on calendar/date rules.'
    )
    parser.add_argument('input_zip', help='Path to input GTFS .zip file')
    parser.add_argument('rules_csv', help='Path to exception rules .csv file')
    parser.add_argument('output_zip', help='Path to output GTFS .zip file')
    args = parser.parse_args()

    process_gtfs(args.input_zip, args.rules_csv, args.output_zip)