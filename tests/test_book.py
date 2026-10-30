"""End-to-end tests: PDF structure, page plan, and sanity checks on the real Digitraffic feed."""
import collections
import re

import pytest
from pypdf import PdfReader

from conftest import synthetic_route
from main import compile_book, create_sample_routes
from models import RouteDefinition, StationRowConfig
from renderer import TimetableBookRenderer


def _pages_text(pdf):
    return [p.extract_text() or "" for p in PdfReader(pdf).pages]


def _to_min(s):
    return int(s[:2]) * 60 + int(s[3:])


def test_synthetic_book_toc_points_to_right_pages(synthetic_loaded, tmp_path):
    imp, trips = synthetic_loaded
    routes = [synthetic_route()]
    for lang in ("fi", "sv"):
        out = str(tmp_path / f"b_{lang}.pdf")
        res = compile_book(lang=lang, output_pdf=out, importer=imp, all_trips=trips, routes=routes)
        pages = _pages_text(out)
        assert len(pages) == res["pages"]
        toc = pages[1]
        assert ("SISÄLLYS" if lang == "fi" else "INNEHÅLL") in toc
        p = res["table_pages"]["1"]
        assert routes[0].get_title(lang) in pages[p - 1]
        assert re.search(rf"{routes[0].get_title(lang)}\s*{p}", toc)


def test_many_routes_toc_spans_pages(synthetic_loaded, tmp_path):
    imp, trips = synthetic_loaded
    base = synthetic_route()
    routes = [RouteDefinition(str(i), f"Taulu {i}", f"Tabell {i}", base.station_rows) for i in range(1, 61)]
    out = str(tmp_path / "many.pdf")
    res = compile_book(lang="fi", output_pdf=out, importer=imp, all_trips=trips, routes=routes)
    pages = _pages_text(out)
    for tid in ("1", "35", "60"):
        assert f"Taulu {tid}" in pages[res["table_pages"][tid] - 1]


def test_station_index_paginates_without_dropping(tmp_path):
    out = str(tmp_path / "idx.pdf")
    r = TimetableBookRenderer(out, "fi")
    names = {f"Asema{i:03d}": ["7"] for i in range(400)}
    r.render_station_index(names)
    r.save()
    text = " ".join(_pages_text(out))
    assert all(n in text for n in names)
    assert len(PdfReader(out).pages) == r.index_pages_needed(list(names)) > 1


def test_too_many_rows_raises(tmp_path):
    r = TimetableBookRenderer(str(tmp_path / "x.pdf"))
    route = RouteDefinition("9", "x", "x", [StationRowConfig(f"S{i}") for i in range(200)])
    with pytest.raises(ValueError):
        r.render_timetable_page(route, [], {})


def test_empty_table_renders(synthetic_loaded, tmp_path):
    imp, trips = synthetic_loaded
    route = RouteDefinition("2", "Tyhjä", "Tom", [StationRowConfig("A"), StationRowConfig("B")],
                            filter_stations=["A", "B"], excluded_train_types={"IC"})
    out = str(tmp_path / "empty.pdf")
    res = compile_book(lang="fi", output_pdf=out, importer=imp, all_trips=trips, routes=[route], drop_empty=False)
    assert "Ei junia" in _pages_text(out)[res["table_pages"]["2"] - 1]
    res = compile_book(lang="fi", output_pdf=out, importer=imp, all_trips=trips, routes=[route])
    assert [r.table_id for r in res["omitted"]] == ["2"] and "2" not in res["table_pages"]


# ---------------------------------------------------------------- real feed
@pytest.fixture(scope="module")
def real_book(real_loaded, tmp_path_factory):
    imp, trips = real_loaded
    out = str(tmp_path_factory.mktemp("real") / "fi.pdf")
    return imp, compile_book(lang="fi", output_pdf=out, importer=imp, all_trips=trips)


def test_real_every_column_runs_forward(real_book):
    """Consecutive times down a column must never go backwards (mod 24 h, < 12 h steps)."""
    _, res = real_book
    for route, chunks in res["compiled"]:
        rows = route.station_rows
        for col in (c for ch in chunks for c in ch):
            seq = [col.times[i] for i, r in enumerate(rows)
                   if not r.is_connection and col.times.get(i) not in (None, "", "|")]
            for a, b in zip(seq, seq[1:]):
                step = (_to_min(b) - _to_min(a)) % 1440
                assert step < 12 * 60, f"table {route.table_id} {col.trip.train_type} {col.trip.train_number}: {seq}"


def _route(res, table_id, first_word):
    return next((r, ch) for r, ch in res["compiled"] if r.table_id == table_id and r.title_fi.startswith(first_word))


def test_real_table7_membership(real_book):
    _, res = real_book
    route, chunks = _route(res, "7", "Helsinki")
    cols = [c for ch in chunks for c in ch]
    assert 10 < len(cols) < 120
    ends = {c.trip.stops[-1].station_code for c in cols}
    assert not ends & {"TKU", "TPE", "PRI", "KUO", "JNS", "HKI"}, ends
    names = {f"{c.trip.train_type} {c.trip.train_number}" for c in cols}
    assert "S 29" in names, "overnight northbound S 29 (Oulu 24:16) must be included"
    assert "S 32" not in names, "southbound S 32 must not be included"


def test_real_feeder_rows_are_before_main_departure(real_book):
    imp, res = real_book
    route, chunks = _route(res, "7", "Helsinki")
    rows = route.station_rows
    pri = next(i for i, r in enumerate(rows) if r.station_code == "PRI")
    tpe_dep = pri + 1
    shown = 0
    for col in (c for ch in chunks for c in ch):
        if col.times.get(pri):
            shown += 1
            wait = (_to_min(col.times[tpe_dep]) - _to_min(col.times[pri])) % 1440
            assert 60 <= wait <= 4 * 60, (col.trip.train_number, col.times[pri], col.times[tpe_dep])
    assert shown > 0


def test_real_pdf_text(real_book):
    imp, res = real_book
    pages = _pages_text(res["pdf"])
    text = "\n".join(pages)
    for raw in ("PNX", "KNU", "LOI", "HUM"):
        assert raw not in text
    index_text = "\n".join(pages[res["index_page"] - 1:])
    for name in ("Pännäinen", "Kannus", "Loimaa", "Humppila", "Hanko", "Kotka", "Savonlinna"):
        assert name in index_text
    for table_id, page in res["table_pages"].items():
        assert re.search(rf"\b{table_id}\b", pages[page - 1])
    assert "SISÄLLYS" in pages[1]


def test_real_sample_routes_codes_exist(real_loaded):
    imp, _ = real_loaded
    for r in create_sample_routes():
        for s in r.station_rows:
            assert s.station_code in imp.station_names, s.station_code


def test_style_colors_and_fonts(real_book):
    """Timetable pages use the #F69679 banner, true red feeder rows and the bundled condensed font."""
    imp, res = real_book
    reader = PdfReader(res["pdf"])
    page = reader.pages[res["table_pages"]["7"] - 1]
    content = page.get_contents().get_data().decode("latin-1")
    fills = {tuple(round(float(v), 3) for v in m) for m in re.findall(r"([\d.]+) ([\d.]+) ([\d.]+) rg", content)}
    banner = tuple(round(v / 255, 3) for v in (0xF6, 0x96, 0x79))
    red = tuple(round(v / 255, 3) for v in (0xE2, 0x00, 0x1A))
    assert banner in fills, fills
    assert red in fills, fills
    pinkish = [f for f in fills if f[0] > 0.8 and f[2] > 0.5 and f[1] < 0.6]   # magenta-like colours
    assert not pinkish, pinkish
    fonts = {str(f["/BaseFont"]) for f in page["/Resources"]["/Font"].values()}
    assert any("Barlow" in f for f in fonts), fonts


def test_real_explicit_dates_become_footnotes(real_book):
    imp, res = real_book
    route, chunks = _route(res, "7", "Helsinki")
    first_page = chunks[0]
    assert any(col.note for col in first_page), "irregular trains get a footnote"
    assert not any("*" in col.days_str or any(ch.isdigit() for ch in col.days_str) for col in first_page), \
        "the operating-days row carries no exception marks"
    text = _pages_text(res["pdf"])[res["table_pages"]["7"] - 1]
    assert re.search(r"\d+\.\d+\.-\d+\.\d+\.\s*M-", text), "footnote with a validity period"



def test_real_all_booklet_tables_present_both_directions(real_book):
    """Every domestic table of the 2007 booklet is in the book, in both directions."""
    _, res = real_book
    expected = {"1", "2", "3", "4", "5", "6", "7", "7A", "8", "9", "10", "11", "12", "12A", "13", "14",
                "14A", "15", "16", "17", "18", "19", "30"}
    ids = collections.Counter(r.table_id for r, _ in res["compiled"])
    assert set(ids) == expected, set(ids) ^ expected
    assert all(n == 2 for n in ids.values()), ids
    toc = [e[0] for e in res["toc_entries"] if e[0]]
    assert toc == sorted(set(toc), key=toc.index) and len(toc) == len(expected), "each table once in the TOC"


def test_real_branch_tables_have_their_own_trains(real_book):
    _, res = real_book
    for tid, word, own in (("2", "Helsinki", "HNK"), ("12", "Helsinki", "KTS"), ("4", "Helsinki", "PRI"),
                           ("19", "Parikkala", "SL"), ("30", "Oulu", "HPA")):
        route, chunks = _route(res, tid, word)
        cols = [c for ch in chunks for c in ch]
        assert cols, tid
        assert any(own in {s.station_code for s in c.trip.stops} for c in cols), (tid, own)


def test_real_onward_connection_rows(real_book):
    """'.o' connection rows show a later arrival at the connection station."""
    _, res = real_book
    route, chunks = _route(res, "1", "Turku")
    rows = route.station_rows
    i = next(k for k, r in enumerate(rows) if r.is_connection and r.is_arrival)
    j = max(k for k in range(i) if not rows[k].is_connection)          # junction arrival row
    shown = 0
    for col in (c for ch in chunks for c in ch):
        if col.times.get(i) and col.times.get(j) not in (None, "", "|"):
            shown += 1
            assert (_to_min(col.times[i]) - _to_min(col.times[j])) % 1440 < 4 * 60
    assert shown > 0


def test_real_night_trains_have_sleeper_only_they(real_loaded):
    from models import ServiceType
    _, trips = real_loaded
    pyo = [t for t in trips if t.train_type == "PYO"]
    assert pyo and all(ServiceType.SLEEPER in t.services for t in pyo)
    assert not any(ServiceType.SLEEPER in t.services for t in trips if t.train_type != "PYO")
    allowed = {ServiceType.BICYCLE, ServiceType.SLEEPER, ServiceType.WHEELCHAIR}
    assert all(t.services <= allowed for t in trips)


def _label_page(tmp_path, ttype, tnum, monkeypatch=None):
    from datetime import date
    from models import TrainTrip
    from table_compiler import CompiledColumn
    r = TimetableBookRenderer(str(tmp_path / f"lbl_{ttype}.pdf"))
    trip = TrainTrip("t", tnum, ttype, {date(2027, 1, 4)})
    col = CompiledColumn(trip, "M-S")
    route = RouteDefinition("9", "x", "x", [StationRowConfig("A"), StationRowConfig("B")])
    r.render_timetable_page(route, [col] * 3, {})
    r.save()
    return PdfReader(str(tmp_path / f"lbl_{ttype}.pdf")).pages[0]


def test_plain_train_type_keeps_number_size(tmp_path):
    """HDM etc. are set in the train-number font at full size; long labels are narrowed (Tz), not shrunk."""
    page = _label_page(tmp_path, "HDM", "1029")
    content = page.get_contents().get_data().decode("latin-1")
    sizes = {float(x) for x in re.findall(r"/F[\w+]+ ([\d.]+) Tf", content)}
    assert 6.5 in sizes and not any(4.0 <= s_ < 6.3 for s_ in sizes - {5.5}), sizes
    assert re.search(r"[\d.]+ Tz", content), "horizontal scaling used for the too-wide label"


def test_user_logo_image_replaces_badge(tmp_path, monkeypatch):
    from PIL import Image
    import style_config as sc
    logo = tmp_path / "IC.png"
    Image.new("RGBA", (40, 20), (0, 0, 0, 255)).save(logo)
    monkeypatch.setitem(sc.TRAIN_TYPE_LOGO_FILES, "IC", [str(logo)])
    TimetableBookRenderer._logo_cache.clear()
    page = _label_page(tmp_path, "IC", "29")
    assert page["/Resources"].get("/XObject"), "logo drawn as an image"



def test_user_svg_logo_is_vector(tmp_path, monkeypatch):
    import style_config as sc
    svg = tmp_path / "IC.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect x="0" y="0" '
                   'width="40" height="20" fill="#123456"/></svg>')
    monkeypatch.setitem(sc.TRAIN_TYPE_LOGO_FILES, "IC", [str(svg)])
    monkeypatch.setattr(sc, "LOGO_RECOLOR", None)
    TimetableBookRenderer._logo_cache.clear()
    page = _label_page(tmp_path, "IC", "29")
    content = page.get_contents().get_data().decode("latin-1")
    assert re.search(r"0?\.070588 0?\.203922 0?\.337255 rg", content), "SVG drawn as vector paths"
    assert not page["/Resources"].get("/XObject"), "no raster image"



def test_svg_logo_recolored_black(tmp_path, monkeypatch):
    import style_config as sc
    svg = tmp_path / "IC.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
                   '<rect width="40" height="20" fill="#E2001A"/><rect x="5" y="5" width="10" height="10" fill="#ffffff"/></svg>')
    monkeypatch.setitem(sc.TRAIN_TYPE_LOGO_FILES, "IC", [str(svg)])
    TimetableBookRenderer._logo_cache.clear()
    content = _label_page(tmp_path, "IC", "29").get_contents().get_data().decode("latin-1")
    assert not re.search(r"0?\.886275 0? 0?\.101961 rg", content), "red replaced"
    assert re.search(r"\b1 1 1 rg", content), "white kept"



def test_raster_logo_recolored_and_transparent(tmp_path, monkeypatch):
    from PIL import Image
    import style_config as sc
    from renderer import _prepare_raster_logo
    src = tmp_path / "IC.jpg"
    im = Image.new("RGB", (60, 30), (255, 255, 255))
    for x in range(10, 50):
        for y in range(8, 22):
            im.putpixel((x, y), (226, 0, 26))
    im.save(src, quality=95)
    out = _prepare_raster_logo(str(src))
    assert out.size[0] < 60 and out.size[1] < 30, "cropped to the symbol"
    r, g, b, a = out.getpixel((out.size[0] // 2, out.size[1] // 2))
    assert (r, g, b) == (26, 26, 26) and a > 200, "red ink became black"
