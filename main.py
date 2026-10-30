"""
main.py - Pipeline coordinator for Finnish and Swedish timetable books.

Usage:
    python main.py [--gtfs gtfs-passenger-stops.zip] [--start 2026-10-16] [--end 2026-12-12]
                   [--lang fi sv] [--outdir .]
Without --start/--end the book covers the feed start up to the next timetable change.
"""
import argparse
import json
import os
import sys
from datetime import date
from typing import List, Dict, Optional, Tuple
import style_config as sc
from models import RouteDefinition, StationRowConfig, TrainTrip
from gtfs_importer import GTFSImporter
from table_compiler import TableCompiler
from renderer import TimetableBookRenderer


ROUTES_FILE = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "routes.json")


def load_routes(path: str = ROUTES_FILE) -> List[RouteDefinition]:
    """Timetable tables of the book (both directions share a table number), see routes.json.
    The structure (stations, km, arrival/departure rows, connection rows) follows the 2007
    VR timetable booklet; `filter_groups` are each table's own line sections."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    routes = []
    for d in data:
        rows = [StationRowConfig(station_code=r["station"], km=r.get("km"), is_arrival=r.get("arrival", False),
                                 is_connection=r.get("connection", False),
                                 display_name_override=r.get("name")) for r in d["rows"]]
        routes.append(RouteDefinition(table_id=d["table_id"], title_fi=d["title_fi"], title_sv=d["title_sv"],
                                      station_rows=rows, filter_stations=d.get(
                                          "filter_stations", []),
                                      filter_groups=d.get("filter_groups", []),
                                      excluded_train_types=set(
                                          d.get("excluded_train_types", [])),
                                      include_commuter=d.get("include_commuter", False)))
    return routes


def create_sample_routes() -> List[RouteDefinition]:
    """Backwards-compatible name for the book's table list."""
    return load_routes()


def validate_routes(routes: List[RouteDefinition], station_names: Dict[str, Dict[str, str]]):
    keys = [(r.table_id, r.title_fi) for r in routes]
    dups = sorted({k for k in keys if keys.count(k) > 1})
    if dups:
        raise ValueError(
            f"Duplicate table_id(s): {dups}. Each table direction needs its own title.")
    for r in routes:
        missing = sorted(
            {s.station_code for s in r.station_rows if s.station_code not in station_names})
        if missing:
            print(
                f"[WARN] Table {r.table_id}: unknown station codes {missing}")


def compile_book(gtfs_path: str = "gtfs-passenger-stops.zip", lang: str = "fi",
                 output_pdf: Optional[str] = None, importer: Optional[GTFSImporter] = None,
                 all_trips: Optional[List[TrainTrip]] = None,
                 start: Optional[date] = None, end: Optional[date] = None,
                 routes: Optional[List[RouteDefinition]] = None, drop_empty: bool = True,
                 map_path: Optional[str] = None, notes_pages: int = 0) -> Dict:
    """Builds one book. Pass `importer` + `all_trips` to reuse an already loaded feed.
    Returns a summary dict (page numbers per table etc.) for logging and tests."""
    if not output_pdf:
        output_pdf = f"Aikataulukirja_{lang.upper()}.pdf"

    if importer is None or all_trips is None:
        if not os.path.exists(gtfs_path):
            raise FileNotFoundError(f"Could not find '{gtfs_path}'.")
        importer = GTFSImporter(gtfs_path)
        all_trips = importer.load_feed(start, end)

    print(f"\n--- Compiling Timetable Book [{lang.upper()}] ---")
    w_start, w_end = importer.window
    validity_str = f"{w_start.strftime('%d.%m.%Y')} – {w_end.strftime('%d.%m.%Y')}" if w_start and w_end else ""

    routes = routes if routes is not None else create_sample_routes()
    validate_routes(routes, importer.station_names)
    renderer = TimetableBookRenderer(output_pdf, lang=lang)
    compiler = TableCompiler(max_columns_per_page=renderer.columns_per_page(), lang=lang, window=importer.window,
                             station_coords=importer.station_coords)

    map_file = map_path or getattr(sc, "MAP_PATH", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "map", "map.svg"))
    has_map = bool(map_file and os.path.exists(map_file))

    # Compile everything first so train counts and contents are known before planning pages
    compiled: List[Tuple[RouteDefinition, list]] = []
    omitted: List[RouteDefinition] = []
    station_index_map: Dict[str, List[str]] = {}
    for route in routes:
        page_chunks = compiler.compile_route(route, all_trips)
        n_cols = sum(len(ch) for ch in page_chunks)
        if n_cols == 0 and drop_empty:
            omitted.append(route)
            continue
        compiled.append((route, page_chunks))
        print(f"[INFO] Table {route.table_id} ({route.get_title(lang)}): {n_cols} train columns "
              f"across {max(len(page_chunks), 1)} page chunk(s).")
        for s in route.station_rows:
            if not s.is_connection:
                loc_name = s.display_name_override or importer.station_names.get(
                    s.station_code, {}).get(lang, s.station_code)
                tables = station_index_map.setdefault(loc_name, [])
                if route.table_id not in tables:
                    tables.append(route.table_id)
    for r in omitted:
        print(
            f"[INFO] Table {r.table_id} ({r.get_title(lang)}) omitted: no trains in the selected period.")

    # -------------------------------------------------------------
    # Page Plan: cover -> TOC -> symbols -> [map] -> station index -> timetables
    # -------------------------------------------------------------
    first_titles: Dict[str, str] = {}
    for route, _ in compiled:
        first_titles.setdefault(route.table_id, route.get_title(lang))

    n_toc_entries = len(first_titles) + 2 + (1 if has_map else 0)
    toc_pages = renderer.toc_pages_needed(n_toc_entries)

    symbols_page = 2 + toc_pages
    map_page = (symbols_page + 1) if has_map else None

    # Station index comes right after symbols / map
    index_start_page = (map_page + 1) if has_map else (symbols_page + 1)
    index_pages = renderer.index_pages_needed(station_index_map)

    # TOC entries in the new order
    toc_entries = [("", renderer.t["toc_symbols"], symbols_page)]
    if has_map:
        toc_entries.append(("", renderer.t["toc_map"], map_page))
    toc_entries.append(("", renderer.t["toc_index"], index_start_page))

    # Timetables start immediately after the station index
    table_pages: Dict[str, int] = {}
    route_pages: List[int] = []

    sim_page = index_start_page + index_pages
    cursor_y = sc.PAGE_HEIGHT - sc.MARGIN_TOP
    tables_on_page = 0
    sim_page_title: Optional[str] = None

    for route, chunks in compiled:
        chunk_list = chunks if chunks else [[]]
        first_p = None
        for col_chunk in chunk_list:
            route_title = route.get_title(lang)
            shares_title = (tables_on_page >
                            0 and sim_page_title == route_title)
            gap = sc.CONTINUED_TABLE_GAP if shares_title else (
                sc.TABLE_STACK_GAP if tables_on_page > 0 else 0.0)
            show_banner = not shares_title
            table_h = renderer.compute_table_height(
                route, col_chunk, show_banner=show_banner)
            if tables_on_page > 0:
                if tables_on_page >= 2 or (cursor_y - gap - table_h < sc.MARGIN_BOTTOM):
                    sim_page += 1
                    cursor_y = sc.PAGE_HEIGHT - sc.MARGIN_TOP
                    tables_on_page = 0
                    sim_page_title = None
                    gap = 0.0
                    show_banner = True
                    table_h = renderer.compute_table_height(
                        route, col_chunk, show_banner=True)
            if first_p is None:
                first_p = sim_page
            tables_on_page += 1
            sim_page_title = route_title
            cursor_y = cursor_y - gap - table_h
            if tables_on_page >= 2:
                sim_page += 1
                cursor_y = sc.PAGE_HEIGHT - sc.MARGIN_TOP
                tables_on_page = 0
                sim_page_title = None

        if route.table_id not in table_pages:
            table_pages[route.table_id] = first_p
            toc_entries.append(
                (route.table_id, first_titles[route.table_id], first_p))
        route_pages.append(first_p)

    # -------------------------------------------------------------
    # Rendering Phase
    # -------------------------------------------------------------
    # 1. Cover
    renderer.render_cover_page(validity_str)

    # 2. Table of Contents
    renderer.render_toc(toc_entries)

    # 3. Symbol Explanations
    _check_page(renderer, symbols_page)
    renderer.render_symbol_explanations()

    # 4. Map (if present)
    if has_map:
        _check_page(renderer, map_page)
        renderer.render_map_page(map_file)

    # 5. Station Index
    _check_page(renderer, index_start_page)
    renderer.render_station_index(station_index_map)

    # 6. Timetable Tables
    for (route, chunks), first_page in zip(compiled, route_pages):
        chunk_list = chunks if chunks else [[]]
        for idx, col_chunk in enumerate(chunk_list):
            act_page = renderer.render_timetable_page(
                route, col_chunk, importer.station_names, is_continued=(idx > 0))
            if idx == 0:
                _check_page(act_page, first_page)

    # 7. Notes Pages
    renderer.flush_page()
    for _ in range(notes_pages):
        renderer.render_notes_page()

    renderer.flush_page()
    renderer.save()

    print(
        f"[SUCCESS] Book compiled: {output_pdf} ({renderer.current_page_num - 1} pages)")
    return {"pdf": output_pdf, "table_pages": table_pages, "route_pages": route_pages,
            "pages": renderer.current_page_num - 1, "compiled": compiled, "toc_entries": toc_entries,
            "omitted": omitted, "index_page": index_start_page, "map_page": map_page}


def _check_page(actual_or_renderer, expected: int):
    actual = actual_or_renderer.current_page_num if hasattr(
        actual_or_renderer, "current_page_num") else actual_or_renderer
    if actual != expected:
        raise RuntimeError(
            f"Page plan mismatch: at page {actual}, expected {expected}")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Build VR timetable books (PDF) from a Digitraffic GTFS feed.")
    p.add_argument("--gtfs", default="gtfs-passenger-stops.zip")
    p.add_argument("--start", type=_parse_date,
                   help="first date of the book period (YYYY-MM-DD)")
    p.add_argument("--end", type=_parse_date,
                   help="last date of the book period (YYYY-MM-DD)")
    p.add_argument("--lang", nargs="+",
                   default=["fi", "sv"], choices=["fi", "sv"])
    p.add_argument("--outdir", default=".")
    p.add_argument("--map", default=None,
                   help="path to map SVG file (default: map/map.svg)")
    p.add_argument("--notes", type=int, default=0,
                   help="number of notes pages to append at the end of the book (default: 0)")
    args = p.parse_args(argv)

    if not os.path.exists(args.gtfs):
        print(
            f"[ERROR] Could not find '{args.gtfs}'. Please place it in the script directory.")
        sys.exit(1)

    try:
        importer = GTFSImporter(args.gtfs)
        trips = importer.load_feed(args.start, args.end)
        os.makedirs(args.outdir, exist_ok=True)
        for lang in args.lang:
            out = os.path.join(
                args.outdir, f"taskuaikataulu_{lang.upper()}.pdf")
            compile_book(args.gtfs, lang=lang, output_pdf=out,
                         importer=importer, all_trips=trips, map_path=args.map,
                         notes_pages=args.notes)
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
