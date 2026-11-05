from table_compiler import CompiledColumn
from models import RouteDefinition, ServiceType
import style_config as sc
from typing import List, Dict, Tuple, Optional
import os
from svglib.svglib import svg2rlg
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics

"""
renderer.py - Renders Finnish and Swedish railway timetable books.
"""

I18N = {
    "fi": {
        "cover_title": "Taskuaikataulu",
        "cover_subtitle": "Kaukoliikenne",
        "toc_title": "SISÄLLYS",
        "timetables": "AIKATAULUT",
        "symbols_title": "MERKKIEN SELITYKSET",
        "operating_days": "Kulkupäivät",
        "train_types": "Junatyypit",
        "timetable_marks": "Aikataulumerkit",
        "services": "Palvelut",
        "station_index_title": "HENKILÖASEMIEN LUETTELO",
        "station_index_subtitle": "Numerot viittaavat aikatauluihin.",
        "toc_symbols": "Merkkien selitykset",
        "toc_map": "Reittikartta",
        "map_title": "REITTIKARTTA",
        "toc_index": "Henkilöasemien luettelo",
        "continued": "",
        "no_trains": "Ei junia valitulla aikavälillä.",
        "km": "km",
        "arrival_mark": ".o",
        "attribution_notice": "Aikataulutiedot: Fintraffic / digitraffic.fi, lisenssi CC BY 4.0",
        "attribution_link": "https://creativecommons.org/licenses/by/4.0/deed.fi",
        "disclaimer": "Oikeudet aikataulumuutoksiin pidätetään.",
        "notes_title": "MUISTIINPANOJA",
        "toc_notes": "Muistiinpanoja",
        "days_legend": [
            ("M", "= maanantai"), ("Ti", "= tiistai"), ("K", "= keskiviikko"),
            ("To", "= torstai"), ("P", "= perjantai"),
            ("L", "= lauantai"), ("S", "= sunnuntai")
        ],
        "types_legend": [
            ("S", "= Pendolino"), ("SP", "= Pendolino Plus"),
            ("IC", "= InterCity"), ("PYO", "= Yöjuna"),
            ("HDM", "= Kiskobussi"), ("H", "= Taajamajuna")
        ],
        "marks_legend": [
            ("|", "= juna kulkee pysähtymättä ohitse"),
            (":", "= juna kulkee toista reittiä"),
            ("o", "= tuloaika asemalle"),
            ("__note__", "= poikkeavat kulkupäivät, katso alaviite"),
            ("__hatch__", "= ei kulje koko aikataulukauden"),
            ("punainen", "= jatkoyhteys tai vaihtojuna"),
        ],
        "services_legend": [
            (ServiceType.SLEEPER, "= makuuvaunu"),
            (ServiceType.BICYCLE, "= polkupyörän kuljetus"),
        ],
    },
    "sv": {
        "cover_title": "Tidtabell",
        "cover_subtitle": "Fjärrtrafik",
        "toc_title": "INNEHÅLL",
        "timetables": "TIDTABELLER",
        "symbols_title": "TECKENFÖRKLARING",
        "operating_days": "Gångdagar",
        "train_types": "Tågtyper",
        "timetable_marks": "Tidtabellstecken",
        "services": "Tjänster",
        "station_index_title": "STATIONSFÖRTECKNING",
        "station_index_subtitle": "Siffrorna hänvisar till tidtabellsnumren.",
        "toc_symbols": "Teckenförklaring",
        "toc_map": "Ruttkarta",
        "map_title": "RUTTKARTA",
        "toc_index": "Förteckning över persontågstationer",
        "continued": "",
        "no_trains": "Inga tåg under den valda perioden.",
        "km": "km",
        "arrival_mark": ".o",
        "attribution_notice": "Tidtabellsuppgifter: Fintraffic / digitraffic.fi, licens CC BY 4.0",
        "attribution_link": "https://creativecommons.org/licenses/by/4.0/deed.sv",
        "disclaimer": "Rätt till tidtabellsändringar förbehålls.",
        "notes_title": "ANTECKNINGAR",
        "toc_notes": "Anteckningar",
        "days_legend": [
            ("M", "= måndag"), ("Ti", "= tisdag"), ("O", "= onsdag"),
            ("To", "= torsdag"), ("F", "= fredag"),
            ("L", "= lördag"), ("S", "= söndag")
        ],
        "types_legend": [
            ("S", "= Pendolino"), ("SP", "= Pendolino Plus"),
            ("IC", "= InterCity"), ("PYO", "= Nattåg"),
            ("HDM", "= Rälsbuss"), ("H", "= Regionaltåg")
        ],
        "marks_legend": [
            ("|", "= tåget stannar inte"),
            (":", "= tåget går en annan väg"),
            ("o", "= ankomsttid till stationen"),
            ("__note__", "= avvikande trafikdagar, se fotnot"),
            ("__hatch__", "= trafikerar inte hela tidtabellsperioden"),
            ("röd", "= bytes- eller anslutningsförbindelse"),
        ],
        "services_legend": [
            (ServiceType.SLEEPER, "= sovvagn"),
            (ServiceType.BICYCLE, "= cykeltransport"),
        ],
    }
}

# Finnish and Swedish both sort Å, Ä, Ö (in that order) after Z.
_SORT_MAP = str.maketrans({"å": "{", "ä": "|", "æ": "|", "ö": "}", "ø": "}", "ü": "y",
                           "é": "e", "è": "e", "á": "a", "à": "a", "w": "v"})


def station_sort_key(name: str) -> str:
    return name.lower().translate(_SORT_MAP)


# ---------------------------------------------------------------- pictograms
ICON_WIDTH = {
    ServiceType.RESTAURANT: 0.62,
    ServiceType.WHEELCHAIR: 0.95,
    ServiceType.SLEEPER: 1.15,
    ServiceType.BICYCLE: 1.25,
}


def icon_width(service: ServiceType, size: float) -> float:
    return ICON_WIDTH.get(service, 1.0) * size


def draw_service_icon(c: canvas.Canvas, service: ServiceType, x: float, y: float, size: float = 6.4):
    """Draw a solid pictogram with its lower-left corner at (x, y)."""
    h = size
    c.saveState()
    c.setStrokeColor(sc.COLOR_TEXT_BLACK)
    c.setFillColor(sc.COLOR_TEXT_BLACK)
    c.setLineCap(1)
    c.setLineJoin(1)
    if service == ServiceType.RESTAURANT:          # fork and knife
        tine, gap = 0.065 * h, 0.05 * h
        fw = 3 * tine + 2 * gap
        for k in range(3):
            c.rect(x + k * (tine + gap), y + 0.6 * h,
                   tine, 0.4 * h, fill=1, stroke=0)
        c.roundRect(x, y + 0.47 * h, fw, 0.18 * h, 0.06 * h, fill=1, stroke=0)
        c.rect(x + fw / 2 - 0.055 * h, y, 0.11 * h, 0.5 * h, fill=1, stroke=0)
        kx = x + fw + 0.12 * h
        p = c.beginPath()
        p.moveTo(kx, y + 0.42 * h)
        p.lineTo(kx, y + h)
        p.curveTo(kx + 0.2 * h, y + 0.95 * h, kx + 0.2 * h,
                  y + 0.6 * h, kx + 0.17 * h, y + 0.42 * h)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        c.rect(kx, y, 0.11 * h, 0.45 * h, fill=1, stroke=0)
    elif service == ServiceType.WHEELCHAIR:        # International symbol of access, solid
        c.circle(x + 0.36 * h, y + 0.88 * h, 0.11 * h, fill=1, stroke=0)
        c.setLineWidth(0.14 * h)
        p = c.beginPath()
        p.moveTo(x + 0.34 * h, y + 0.68 * h)
        p.lineTo(x + 0.36 * h, y + 0.42 * h)
        p.lineTo(x + 0.68 * h, y + 0.42 * h)
        p.lineTo(x + 0.84 * h, y + 0.08 * h)
        c.drawPath(p, fill=0, stroke=1)
        c.setLineWidth(0.09 * h)
        c.line(x + 0.36 * h, y + 0.58 * h, x + 0.6 * h, y + 0.58 * h)
        p = c.beginPath()                           # wheel, open towards the seat
        p.arc(x + 0.06 * h, y + 0.0 * h, x + 0.62 * h,
              y + 0.56 * h, startAng=-20, extent=-250)
        c.drawPath(p, fill=0, stroke=1)
    elif service == ServiceType.SLEEPER:           # bed
        w = 1.15 * h
        c.rect(x, y, 0.11 * h, 0.8 * h, fill=1, stroke=0)
        c.rect(x, y + 0.24 * h, w, 0.2 * h, fill=1, stroke=0)
        c.rect(x + w - 0.11 * h, y, 0.11 * h, 0.44 * h, fill=1, stroke=0)
        c.roundRect(x + 0.16 * h, y + 0.48 * h, 0.3 * h,
                    0.17 * h, 0.06 * h, fill=1, stroke=0)
        c.roundRect(x + 0.5 * h, y + 0.48 * h, w - 0.5 * h,
                    0.12 * h, 0.05 * h, fill=1, stroke=0)
    elif service == ServiceType.BICYCLE:           # bicycle
        w = 1.25 * h
        r = 0.27 * h
        c.setLineWidth(0.09 * h)
        c.circle(x + r, y + r, r * 0.92, fill=0, stroke=1)
        c.circle(x + w - r, y + r, r * 0.92, fill=0, stroke=1)
        c.setLineWidth(0.1 * h)
        p = c.beginPath()
        p.moveTo(x + r, y + r)
        p.lineTo(x + 0.5 * w, y + r)
        p.lineTo(x + 0.75 * w, y + 0.62 * h)
        p.lineTo(x + w - r, y + r)
        p.moveTo(x + r, y + r)
        p.lineTo(x + 0.4 * w, y + 0.62 * h)
        p.lineTo(x + 0.75 * w, y + 0.62 * h)
        p.moveTo(x + 0.4 * w, y + 0.62 * h)
        p.lineTo(x + 0.5 * w, y + r)
        p.moveTo(x + 0.36 * w, y + 0.74 * h)
        p.lineTo(x + 0.46 * w, y + 0.74 * h)
        c.drawPath(p, fill=0, stroke=1)
    c.restoreState()


ICON_LINES = [[ServiceType.RESTAURANT], [
    ServiceType.WHEELCHAIR, ServiceType.BICYCLE], [ServiceType.SLEEPER]]


def _prepare_raster_logo(path: str):
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    px = im.load()
    rc = sc.HexColor(sc.LOGO_RECOLOR) if sc.LOGO_RECOLOR else None
    target = tuple(int(round(v * 255))
                   for v in (rc.red, rc.green, rc.blue)) if rc else None
    for yy in range(im.height):
        for xx in range(im.width):
            r, g, b, a = px[xx, yy]
            if a == 0:
                continue
            white = min(r, g, b) / 255.0
            ink = 1.0 - white if min(r, g, b) > 0 else 1.0
            if white > 0.92:
                px[xx, yy] = (255, 255, 255, 0)
            elif target:
                px[xx, yy] = target + (int(a * min(1.0, ink * 1.4)),)
    box = im.getbbox()
    return im.crop(box) if box else im


def _is_whiteish(col) -> bool:
    try:
        return min(col.red, col.green, col.blue) > 0.9
    except AttributeError:
        return False


def _recolor_drawing(node, color):
    for attr in ("fillColor", "strokeColor"):
        col = getattr(node, attr, None)
        if col is not None and not _is_whiteish(col):
            alpha = getattr(col, "alpha", 1)
            try:
                setattr(node, attr, color.clone(
                    alpha=alpha) if alpha != 1 else color)
            except Exception:
                setattr(node, attr, color)
    for child in getattr(node, "contents", []) or []:
        _recolor_drawing(child, color)


class TimetableBookRenderer:
    PAGE_COL = {"fi": "SIVU", "sv": "SIDA"}
    INDEX_COLS = 2

    def __init__(self, filename: str, lang: str = "fi"):
        self.filename = filename
        self.lang = lang
        self.t = I18N.get(lang, I18N["fi"])
        self.pdf = canvas.Canvas(
            filename, pagesize=(sc.PAGE_WIDTH, sc.PAGE_HEIGHT))
        self.pdf.setTitle(self.t["cover_title"])
        self.current_page_num = 1
        self._reset_page_state()

    def _reset_page_state(self):
        """Resets the layout cursor for the start of a fresh page."""
        self.cursor_y = sc.PAGE_HEIGHT - sc.MARGIN_TOP
        self.tables_on_page = 0
        self.current_page_title: Optional[str] = None

    def flush_page(self):
        """Finalizes the current page if any table is open on it."""
        if self.tables_on_page > 0:
            self._finish_page()

    def flush_timetable_page(self):
        self.flush_page()

    def save(self):
        self.flush_page()
        self.pdf.save()

    # ---------------------------------------------------------------- page helpers
    def _finish_page(self, numbered: bool = True):
        """Booklet footer: page number at the outer edge next to a thin vertical rule."""
        if numbered:
            c = self.pdf
            c.setFont(sc.FONT_CONDENSED, sc.PAGE_NUMBER_SIZE)
            c.setFillColor(sc.COLOR_TEXT_BLACK)
            c.setStrokeColor(sc.COLOR_TEXT_BLACK)
            c.setLineWidth(0.3)
            y = 17.0
            if self.current_page_num % 2 == 0:
                x = sc.MARGIN_LEFT
                c.line(x, 4.0, x, 28.5)
                c.drawString(x + 3.8, y, str(self.current_page_num))
            else:
                x = sc.PAGE_WIDTH - sc.MARGIN_RIGHT
                c.line(x, 4.0, x, 28.5)
                c.drawRightString(x - 3.8, y, str(self.current_page_num))
        self.pdf.showPage()
        self.current_page_num += 1
        self._reset_page_state()

    def _fit_font(self, text: str, font: str, size: float, max_w: float, min_size: float = 4.0) -> float:
        while size > min_size and self.pdf.stringWidth(text, font, size) > max_w:
            size -= 0.1
        return size

    def _draw_page_heading(self, title: str) -> float:
        c = self.pdf
        base = sc.PAGE_HEIGHT - sc.MARGIN_TOP - 30
        c.setFillColor(sc.COLOR_TOC_TINT)
        c.rect(sc.MARGIN_LEFT, base - 3, 22, 33, fill=True, stroke=False)
        c.setFillColor(sc.COLOR_TEXT_BLACK)
        c.setFont(sc.FONT_BODY_BOLD, sc.HEADING_SIZE)
        c.drawString(sc.MARGIN_LEFT + 4, base, title)
        rule_y = base - 3.5
        c.setStrokeColor(sc.COLOR_BANNER_BG)
        c.setLineWidth(1.6)
        c.line(sc.MARGIN_LEFT, rule_y, sc.PAGE_WIDTH - sc.MARGIN_RIGHT, rule_y)
        return rule_y

    def _wrap_footnote(self, segs: List[Tuple[str, bool]], max_w: float) -> List[List[Tuple[str, bool]]]:
        """Wrap (text, bold) footnote segments across lines fitting within max_w."""
        lines, cur_line, cur_w = [], [], 0.0
        fs = sc.TEXT_SIZE
        for text, bold in segs:
            font = sc.FONT_CONDENSED_BOLD if bold else sc.FONT_CONDENSED
            for i, word in enumerate(text.split(" ")):
                piece = (" " if i > 0 else "") + word
                w = self.pdf.stringWidth(piece, font, fs)
                if cur_line and cur_w + w > max_w:
                    lines.append(cur_line)
                    cur_line, cur_w = [
                        (word, bold)], self.pdf.stringWidth(word, font, fs)
                else:
                    cur_line.append((piece, bold))
                    cur_w += w
        if cur_line:
            lines.append(cur_line)
        return lines or [[("", False)]]

    # ---------------------------------------------------------------- cover
    def _find_cover_image(self) -> Optional[str]:
        candidate = getattr(sc, "COVER_IMAGE_PATH", None)
        if candidate and os.path.exists(candidate):
            return candidate
        if candidate:
            base, _ = os.path.splitext(candidate)
            for ext in (".jpg", ".jpeg", ".png"):
                if os.path.exists(base + ext):
                    return base + ext
        return None

    def render_cover_page(self, validity_text: str):
        self.flush_page()
        c = self.pdf

        pad_x = getattr(sc, "COVER_PADDING_X", 10.0)
        pad_y = getattr(sc, "COVER_PADDING_Y", 5.0)
        title_font_size = getattr(sc, "TITLE_FONT_SIZE", 20.0)
        subtitle_font_size = getattr(sc, "SUBTITLE_FONT_SIZE", 10.0)
        title_row_h = pad_y + title_font_size + pad_y
        title_bottom = sc.PAGE_HEIGHT - title_row_h
        font = pdfmetrics.getFont(sc.FONT_BODY_BOLD)
        cap_height = (font.face.capHeight / 1000.0) * title_font_size
        title_y = title_bottom + (title_row_h - cap_height) / 2

        # Draw cover image (or neutral background if no image found)
        img_path = self._find_cover_image()
        if img_path:
            c.drawImage(img_path, 0, 0, width=sc.PAGE_WIDTH,
                        height=sc.PAGE_HEIGHT)
        else:
            c.setFillColor(sc.COLOR_WHITE)
            c.rect(0, 0, sc.PAGE_WIDTH, sc.PAGE_HEIGHT, fill=True, stroke=False)

        # 1. Distinct title row with background color and padding
        c.setFillColor(sc.COLOR_COVER_TITLE_BG)
        c.rect(0, title_bottom, sc.PAGE_WIDTH,
               title_row_h, fill=True, stroke=False)

        c.setFillColor(sc.COLOR_COVER_TITLE)
        c.setFont(sc.FONT_BODY_BOLD, title_font_size)
        c.drawString(pad_x, title_y, self.t["cover_title"])

        # 2. Subtitle overlaid on the cover image
        subtitle_y = title_bottom - (subtitle_font_size + pad_y)
        c.setFillColor(sc.COLOR_COVER_SUBTITLE)
        c.setFont(sc.FONT_BODY_BOLD, subtitle_font_size)
        c.drawString(pad_x, subtitle_y, self.t["cover_subtitle"])

        # 3. Validity overlaid on the cover image
        if validity_text:
            validity_y = subtitle_y - (subtitle_font_size + pad_y)
            validity_label = f"{validity_text}"
            c.drawString(pad_x, validity_y, validity_label)

        self._finish_page(numbered=False)

    # ---------------------------------------------------------------- table of contents
    def _toc_first_y(self) -> float:
        return sc.PAGE_HEIGHT - sc.MARGIN_TOP - 30 - 3.5 - 52

    def toc_rows_per_page(self) -> int:
        return max(1, int((self._toc_first_y() - sc.MARGIN_BOTTOM - 6) / sc.TOC_ROW_PITCH) + 1)

    def toc_pages_needed(self, n_entries: int) -> int:
        return max(1, -(-n_entries // self.toc_rows_per_page()))

    def render_toc(self, entries: List[Tuple[str, str, int]]):
        self.flush_page()
        c = self.pdf
        per_page = self.toc_rows_per_page()
        chunks = [entries[i:i + per_page]
                  for i in range(0, len(entries), per_page)] or [[]]
        width = sc.CONTENT_WIDTH * 0.80
        x0 = sc.MARGIN_LEFT
        for chunk_no, chunk in enumerate(chunks):
            title = self.t["toc_title"] + \
                (f" {self.t['continued']}" if chunk_no else "")
            rule_y = self._draw_page_heading(title)
            c.setFillColor(sc.COLOR_TEXT_BLACK)
            c.setFont(sc.FONT_BODY_BOLD, sc.TOC_SIZE)
            c.drawString(x0, rule_y - 28, self.t["timetables"])
            c.setFont(sc.FONT_BODY, 7)
            c.drawRightString(x0 + width - 2, rule_y - 28,
                              self.PAGE_COL.get(self.lang, "SIVU"))

            y = self._toc_first_y()
            for idx, (table_id, title, page) in enumerate(chunk):
                if idx % 2 == 1:
                    c.setFillColor(sc.COLOR_TOC_TINT)
                    c.rect(x0, y - 3.6, width, sc.TOC_ROW_PITCH -
                           1.5, fill=True, stroke=False)
                c.setFillColor(sc.COLOR_TEXT_BLACK)
                c.setFont(sc.FONT_BODY_BOLD, sc.TOC_SIZE)
                c.drawString(x0 + 3, y, str(table_id))
                c.setFont(sc.FONT_BODY, sc.TOC_SIZE)
                c.drawString(x0 + 40, y, title)
                c.drawRightString(x0 + width - 2, y, str(page))
                y -= sc.TOC_ROW_PITCH
            self._finish_page()

    # ---------------------------------------------------------------- map
    def render_map_page(self, map_path: Optional[str] = None):
        """Renders the railway map page inside a black border block with the
        subtitle placed between the main title and the map.
        """
        self.flush_page()
        c = self.pdf
        rule_y = self._draw_page_heading(self.t["map_title"])

        path = map_path or getattr(sc, "MAP_PATH", None)
        pad_top = getattr(sc, "MAP_PADDING_TOP", 8.0)
        pad_bottom = getattr(sc, "MAP_PADDING_BOTTOM", 8.0)
        border_w = getattr(sc, "MAP_BORDER_WIDTH", 0.8)
        inner_pad = getattr(sc, "MAP_INNER_PADDING", 4.0)
        sub_size = getattr(sc, "MAP_SUBTITLE_SIZE", 8.5)
        sub_gap = getattr(sc, "MAP_SUBTITLE_GAP", 5.0)

        subtitle_text = self.t.get("station_index_subtitle", "")

        # 1. Top layout: Title rule -> pad_top -> [subtitle -> sub_gap] -> map box
        if subtitle_text:
            sub_font = getattr(sc, "FONT_BODY")
            subtitle_y = rule_y - pad_top - (sub_size * 0.85)
            c.saveState()
            c.setFillColor(sc.COLOR_TEXT_BLACK)
            c.setFont(sub_font, sub_size)
            c.drawString(sc.MARGIN_LEFT, subtitle_y, subtitle_text)
            c.restoreState()
            box_top = subtitle_y - sub_gap
        else:
            box_top = rule_y - pad_top

        # 2. Bottom layout: Map box ends pad_bottom above the page footer line
        box_x = sc.MARGIN_LEFT
        box_w = sc.CONTENT_WIDTH
        box_bottom = sc.MARGIN_BOTTOM + pad_bottom
        box_h = box_top - box_bottom
        box_y = box_bottom

        drawing = None
        if path and os.path.exists(path):
            try:
                drawing = svg2rlg(path)
                target_font = "Helvetica57-Condensed"
                if target_font in pdfmetrics.getRegisteredFontNames():
                    def _apply_font(node):
                        if hasattr(node, "fontName"):
                            node.fontName = target_font
                        for child in getattr(node, "contents", []) or []:
                            _apply_font(child)
                    _apply_font(drawing)
            except Exception as e:
                print(f"[WARN] Failed to load map SVG '{path}': {e}")
                drawing = None

        dw = getattr(drawing, "width", 0) if drawing else 0
        dh = getattr(drawing, "height", 0) if drawing else 0

        if getattr(sc, "MAP_FIT_BORDER_TO_MAP", False) and dw > 0 and dh > 0:
            avail_w = box_w - 2 * inner_pad
            avail_h = box_h - 2 * inner_pad
            scale = min(avail_w / dw, avail_h / dh)
            box_w = dw * scale + 2 * inner_pad
            box_h = dh * scale + 2 * inner_pad
            box_x = (sc.PAGE_WIDTH - box_w) / 2.0
            box_y = box_top - box_h

        # 3. Draw black border block
        c.saveState()
        c.setStrokeColor(sc.COLOR_TEXT_BLACK)
        c.setFillColor(sc.COLOR_WHITE)
        c.setLineWidth(border_w)
        c.rect(box_x, box_y, box_w, box_h, fill=1, stroke=1)
        c.restoreState()

        # 4. Draw SVG map centered inside the border block with inner_pad
        if drawing is not None and dw > 0 and dh > 0:
            from reportlab.graphics import renderPDF

            avail_w = box_w - 2 * inner_pad
            avail_h = box_h - 2 * inner_pad
            scale = min(avail_w / dw, avail_h / dh)
            scaled_w = dw * scale
            scaled_h = dh * scale
            mx = box_x + (box_w - scaled_w) / 2.0
            my = box_y + (box_h - scaled_h) / 2.0

            c.saveState()
            # Clip strictly inside the inner padding area
            p = c.beginPath()
            p.rect(box_x + inner_pad, box_y + inner_pad, avail_w, avail_h)
            c.clipPath(p, stroke=0, fill=0)

            c.translate(mx, my)
            c.scale(scale, scale)
            renderPDF.draw(drawing, c, 0, 0)
            c.restoreState()

        self._finish_page()

    # ---------------------------------------------------------------- symbols
    def render_symbol_explanations(self):
        self.flush_page()
        c = self.pdf
        rule_y = self._draw_page_heading(self.t["symbols_title"])
        y = rule_y - 22
        pitch = 9.5
        fs = sc.SYMBOLS_SIZE
        icon_sz = sc.ICON_SIZE + 0.6

        def draw_block(x, y, b):
            boxed = b.get("boxed", False)
            tx = x + 6.0 if boxed else x
            key_dx = b.get("key_dx", 20)
            items = b["items"]

            # 1. Block Title
            c.setFillColor(sc.COLOR_TEXT_BLACK)
            c.setFont(sc.FONT_BODY_BOLD, fs + 0.5)
            c.drawString(tx, y, b["title"])

            # 2. Block Items
            ly = y - pitch - 2
            for k, v in items:
                # Key / Icon
                if isinstance(k, ServiceType):
                    draw_service_icon(
                        c, k, tx + (10 - icon_width(k, icon_sz)) / 2, ly - 0.8, icon_sz)
                elif k == "__note__":
                    self._draw_footnote_mark(tx + 3.0, ly + 2.2, "A")
                elif k == "__hatch__":
                    self._draw_hatch(tx, ly - 1.5, tx + 14, ly + 6.5)
                    c.setStrokeColor(sc.COLOR_EXCEPTION_OUTLINE)
                    c.setLineWidth(sc.EXCEPTION_OUTLINE_WIDTH)
                    c.rect(tx, ly - 1.5, 14, 8, fill=0, stroke=1)
                elif b.get("styled_keys") and (lg := self._type_logo(k)):
                    w_ = self._logo_width(lg) * 1.25
                    self._draw_logo(lg, tx, ly, w_, sc.LOGO_HEIGHT * 1.25)
                elif b.get("styled_keys") and k in sc.BADGE_TRAIN_TYPES:
                    self._draw_type_badge(tx, ly, k, 1.25)
                elif b.get("styled_keys") and k in sc.STYLED_TRAIN_TYPES:
                    c.setFillColor(sc.COLOR_TEXT_BLACK)
                    c.setFont(sc.FONT_CONDENSED_ITALIC, fs + 1)
                    c.drawString(tx, ly, k)
                else:
                    c.setFillColor(sc.COLOR_FEEDER_RED if k == b.get(
                        "red_key") else sc.COLOR_TEXT_BLACK)
                    c.setFont(sc.FONT_BODY_BOLD, fs)
                    c.drawString(tx, ly, k)

                # Description text
                c.setFillColor(sc.COLOR_TEXT_BLACK)
                c.setFont(sc.FONT_BODY, fs)
                c.drawString(tx + key_dx, ly, v)
                ly -= pitch

            bottom = y - 4 - len(items) * pitch
            if boxed:
                c.setStrokeColor(sc.COLOR_GRID_LINE)
                c.setLineWidth(0.5)
                c.rect(x, bottom, b.get(
                    "box_w", b["width"]), (y + 12) - bottom)

            return bottom

        red_key = self.t["marks_legend"][-1][0] if self.t["marks_legend"] else None

        blocks = [
            {"title": self.t["operating_days"], "items": self.t["days_legend"],
                "key_dx": 20, "boxed": True, "width": 115.0},
            {"title": self.t["train_types"], "items": self.t["types_legend"], "key_dx": 28,
                "boxed": True, "styled_keys": True, "width": 115.0, "box_w": 100.0},
            {"title": self.t["timetable_marks"], "items": self.t["marks_legend"],
                "key_dx": 34, "red_key": red_key, "width": 230.0},
            {"title": self.t["services"], "items": self.t["services_legend"],
                "key_dx": 13, "width": 115.0},
        ]

        max_x = sc.PAGE_WIDTH - sc.MARGIN_RIGHT
        cur_x, cur_y = sc.MARGIN_LEFT, y
        col_gap, row_gap = 18.0, 20.0
        row_bottom_y = cur_y

        for b in blocks:
            bw = b["width"]
            if cur_x > sc.MARGIN_LEFT and cur_x + bw > max_x:
                cur_x = sc.MARGIN_LEFT
                cur_y = row_bottom_y - row_gap
                row_bottom_y = cur_y

            bottom = draw_block(cur_x, cur_y, b)
            row_bottom_y = min(row_bottom_y, bottom)
            cur_x += bw + col_gap

        # Draw license attribution & changes disclaimer at the bottom of the page
        c.saveState()
        disc_y = sc.MARGIN_BOTTOM + 8.0
        c.setFillColor(sc.COLOR_TEXT_BLACK)
        c.setFont(sc.FONT_BODY, sc.SYMBOLS_SIZE)
        c.drawString(sc.MARGIN_LEFT, disc_y, self.t["disclaimer"])

        attr_text = self.t["attribution_notice"]
        attr_y = disc_y + 8.0
        c.drawString(sc.MARGIN_LEFT, attr_y, attr_text)

        link_url = self.t["attribution_link"]
        w = c.stringWidth(attr_text, sc.FONT_BODY, sc.SYMBOLS_SIZE)
        c.linkURL(link_url, (sc.MARGIN_LEFT, attr_y - 1,
                  sc.MARGIN_LEFT + w, attr_y + 7), relative=0)
        c.restoreState()

        self._finish_page()

    # ---------------------------------------------------------------- timetables
    def columns_per_page(self) -> int:
        return max(1, int((sc.CONTENT_WIDTH - sc.STATION_COL_WIDTH) / sc.TRAIN_COL_PITCH + 1e-6))

    def _draw_table_banner(self, table_id: str, title: str, top_y: float):
        c = self.pdf
        h = sc.BANNER_HEIGHT
        x = sc.MARGIN_LEFT
        x_r = sc.PAGE_WIDTH - sc.MARGIN_RIGHT
        bottom = top_y - h
        c.setStrokeColor(sc.COLOR_GRID_LINE)
        c.setFillColor(sc.COLOR_GRID_LINE)
        c.setLineWidth(sc.BANNER_OUTER_RULE)
        c.line(x, top_y, x_r, top_y)
        c.line(x, bottom, x_r, bottom)
        c.rect(x, bottom, 1.1, h, fill=True, stroke=False)
        c.rect(x_r - 1.1, bottom, 1.1, h, fill=True, stroke=False)
        ix, ix_r = x + 2.8, x_r - 2.8
        itop, ibot = top_y - 2.6, bottom + 2.2
        c.setFillColor(sc.COLOR_BANNER_BG)
        c.rect(ix, ibot, ix_r - ix, itop - ibot, fill=True, stroke=False)
        c.setLineWidth(sc.BANNER_INNER_RULE)
        c.line(ix, itop, ix_r, itop)
        c.line(ix, ibot, ix_r, ibot)
        c.line(ix, ibot, ix, itop)
        c.line(ix_r, ibot, ix_r, itop)
        c.setFillColor(sc.COLOR_TEXT_BLACK)
        tx = x + 9.5
        if table_id:
            c.setFont(sc.FONT_CONDENSED_BOLD, sc.BANNER_NUMBER_SIZE)
            c.drawString(tx, bottom + 4.6, str(table_id))
            tx = max(x + 25.7, tx + c.stringWidth(str(table_id),
                     sc.FONT_CONDENSED_BOLD, sc.BANNER_NUMBER_SIZE) + 6)
        c.setFont(sc.FONT_CONDENSED_BOLD, sc.BANNER_TITLE_SIZE)
        c.drawString(tx, bottom + 6.0, title)
        return bottom

    def _draw_footnote_mark(self, cx: float, cy: float, letter: str):
        c = self.pdf
        c.setStrokeColor(sc.COLOR_FEEDER_RED)
        c.setFillColor(sc.COLOR_WHITE)
        c.setLineWidth(0.5)
        c.circle(cx, cy, sc.FOOTNOTE_MARK_RADIUS, fill=1, stroke=1)
        c.setFillColor(sc.COLOR_FEEDER_RED)
        c.setFont(sc.FONT_CONDENSED_BOLD, 4.9)
        c.drawCentredString(cx, cy - 1.7, letter)

    def _draw_hatch(self, x0: float, y0: float, x1: float, y1: float):
        c = self.pdf
        c.saveState()
        p = c.beginPath()
        p.rect(x0, y0, x1 - x0, y1 - y0)
        c.clipPath(p, stroke=0, fill=0)
        c.setStrokeColor(sc.COLOR_HATCH)
        c.setLineWidth(sc.HATCH_WIDTH)
        c.setLineCap(0)
        h = y1 - y0
        x = x0 - h
        while x < x1:
            c.line(x, y0, x + h, y1)
            x += sc.HATCH_SPACING
        c.restoreState()

    def _draw_exception_frame(self, col_x: float, col_w: float, top: float, hatch_bottom: float, bottom: float):
        c = self.pdf
        x0, x1 = col_x + sc.EXCEPTION_INSET, col_x + col_w - sc.EXCEPTION_INSET
        self._draw_hatch(x0, hatch_bottom, x1, top)
        c.setStrokeColor(sc.COLOR_EXCEPTION_OUTLINE)
        c.setLineWidth(sc.EXCEPTION_OUTLINE_WIDTH)
        c.rect(x0, bottom, x1 - x0, top - bottom, fill=0, stroke=1)

    def _badge_width(self, ttype: str) -> float:
        return self.pdf.stringWidth(ttype, sc.FONT_CONDENSED_BOLD, sc.BADGE_TEXT_SIZE) + 2 * 1.4

    def _draw_type_badge(self, x: float, y: float, ttype: str, scale: float = 1.0):
        c = self.pdf
        w = self._badge_width(ttype) * scale
        h = sc.BADGE_HEIGHT * scale
        c.saveState()
        c.setFillColor(sc.COLOR_TEXT_BLACK)
        c.roundRect(x, y - 0.9 * scale, w, h,
                    sc.BADGE_RADIUS * scale, fill=1, stroke=0)
        c.setFillColor(sc.COLOR_WHITE)
        c.setFont(sc.FONT_CONDENSED_BOLD, sc.BADGE_TEXT_SIZE * scale)
        c.drawCentredString(x + w / 2, y + 0.1 * scale, ttype)
        c.restoreState()
        return w

    _logo_cache: Dict[str, object] = {}

    def _type_logo(self, ttype: str):
        paths = sc.TRAIN_TYPE_LOGO_FILES.get(ttype) or []
        if isinstance(paths, str):
            paths = [paths]
        path = next((p for p in paths if os.path.exists(p)), None)
        if not path:
            return None
        if path not in self._logo_cache:
            if path.lower().endswith(".svg"):
                from svglib.svglib import svg2rlg
                drawing = svg2rlg(path)
                if drawing is not None and sc.LOGO_RECOLOR:
                    _recolor_drawing(drawing, sc.HexColor(sc.LOGO_RECOLOR))
                self._logo_cache[path] = ("svg", drawing) if drawing else None
            else:
                from reportlab.lib.utils import ImageReader
                self._logo_cache[path] = (
                    "img", ImageReader(_prepare_raster_logo(path)))
        return self._logo_cache[path]

    def _logo_width(self, logo) -> float:
        kind, obj = logo
        if kind == "svg":
            iw, ih = obj.width, obj.height
        else:
            iw, ih = obj.getSize()
        return sc.LOGO_HEIGHT * iw / ih

    def _draw_logo(self, logo, x: float, y: float, w: float, h: float):
        kind, obj = logo
        if kind == "svg":
            from reportlab.graphics import renderPDF
            c = self.pdf
            c.saveState()
            c.translate(x, y)
            c.scale(w / obj.width, h / obj.height)
            renderPDF.draw(obj, c, 0, 0)
            c.restoreState()
        else:
            self.pdf.drawImage(obj, x, y, width=w, height=h, mask="auto")

    def _draw_train_label(self, cx: float, y: float, ttype: str, tnum: str, max_w: float):
        c = self.pdf
        fs = sc.TEXT_SIZE
        logo = self._type_logo(ttype) if ttype else None
        badge = logo is None and ttype in sc.BADGE_TRAIN_TYPES
        styled = logo is None and not badge and ttype in sc.STYLED_TRAIN_TYPES
        plain = not (logo or badge or styled)
        tfont, tsize = (sc.FONT_CONDENSED_ITALIC, sc.TRAIN_TYPE_SIZE) if styled else (
            sc.FONT_CONDENSED, fs)
        space = c.stringWidth(" ", sc.FONT_CONDENSED, fs)
        gap = space if plain else 1.2
        if logo is not None:
            w_type = self._logo_width(logo)
        elif badge:
            w_type = self._badge_width(ttype)
        else:
            w_type = c.stringWidth(ttype, tfont, tsize) if ttype else 0.0
        w_num = c.stringWidth(tnum, sc.FONT_CONDENSED, fs)
        total = w_type + (gap if ttype and tnum else 0) + w_num
        c.setFillColor(sc.COLOR_TEXT_BLACK)
        if plain:
            if total > max_w and ttype and tnum:
                gap = 1.0
                total = w_type + gap + w_num
            hscale = min(1.0, max_w / max(total, 1))
            x = cx - total * hscale / 2
            for part, w in ((ttype, w_type), (tnum, w_num)):
                if not part:
                    continue
                t = c.beginText(x, y)
                t.setFont(sc.FONT_CONDENSED, fs)
                t.setHorizScale(hscale * 100)
                t.textOut(part)
                c.drawText(t)
                x += (w + gap) * hscale
            return
        scale = min(1.0, max_w / max(total, 1))
        lx = cx - total * scale / 2
        if logo is not None:
            self._draw_logo(logo, lx, y, w_type * scale,
                            sc.LOGO_HEIGHT * scale)
        elif badge:
            self._draw_type_badge(lx, y, ttype, scale)
        else:
            c.setFont(tfont, tsize * scale)
            c.drawString(lx, y, ttype)
        lx += (w_type + gap) * scale
        c.setFillColor(sc.COLOR_TEXT_BLACK)
        c.setFont(sc.FONT_CONDENSED, fs * scale)
        c.drawString(lx, y, tnum)

    @staticmethod
    def _display_time(t: str) -> str:
        return t[1:] if len(t) == 5 and t[0] == "0" else t

    @staticmethod
    def _row_baselines(rows, header_rule_y: float):
        """Baselines per row plus the y of the block rules (drawn after an arrival row
        only when followed by a departure row of the same station, and around connection rows).
        Spacing follows the booklet: 7.03 pt, 8.1 pt over a rule."""
        baselines, rules = [], []
        y = header_rule_y - sc.FIRST_BASELINE_BELOW_RULE
        for i, r in enumerate(rows):
            if i > 0:
                prev = rows[i - 1]
                arrival_to_dept = (
                    prev.is_arrival
                    and not r.is_arrival
                    and prev.station_code
                    and prev.station_code == r.station_code
                )
                conn_boundary = bool(
                    prev.is_connection) != bool(r.is_connection)
                if arrival_to_dept or conn_boundary:
                    rule_y = baselines[-1] - sc.BLOCK_RULE_BELOW_BASELINE
                    rules.append(rule_y)
                    y = rule_y - sc.BASELINE_BELOW_BLOCK_RULE
                else:
                    y = baselines[-1] - sc.ROW_PITCH
            baselines.append(y)
        return baselines, rules

    def _dot_positions(self, name_end_x: float, first_col_x: float, is_arrival: bool) -> Tuple[List[float], float]:
        last = first_col_x - sc.DOT_LAST_FROM_COLUMN
        if is_arrival:
            last -= sc.DOT_PITCH
        xs = []
        x = last
        while x >= name_end_x + sc.DOT_GAP_AFTER_NAME:
            xs.append(x)
            x -= sc.DOT_PITCH
        return xs[::-1], last + sc.ARRIVAL_O_AFTER_DOT

    def header_height(self, columns: Optional[List[CompiledColumn]] = None) -> float:
        """Determines the compact vertical space needed by the header based on whether
        columns have icons and footnote symbols."""
        if not columns:
            return 26.0
        icon_sz = getattr(sc, "ICON_SIZE", 5.4)
        fn_r = getattr(sc, "FOOTNOTE_MARK_RADIUS", 2.8)
        max_icon_lines = max(
            (sum(1 for line in ICON_LINES if any(
                svc in col.trip.services for svc in line)) for col in columns),
            default=0
        )
        lowest_depth = (21.6 + max_icon_lines * icon_sz +
                        (max_icon_lines - 1) * 1.2) if max_icon_lines > 0 else 20.8
        if any(col.note for col in columns):
            lowest_depth += 1.2 + 2 * fn_r
        return max(26.0, lowest_depth + 3.0)

    def compute_table_height(self, route: RouteDefinition, columns: List[CompiledColumn],
                             show_banner: bool = True) -> float:
        """Exact height in points needed by the timetable, including banner (if show_banner),
        header, rows, rules, and footnotes."""
        banner_h = sc.BANNER_HEIGHT if show_banner else 0.0
        h_h = self.header_height(columns)
        header_rule_y = -(banner_h + h_h)
        baselines, _ = self._row_baselines(route.station_rows, header_rule_y)
        table_bottom = (
            baselines[-1] if baselines else header_rule_y) - sc.BLOCK_RULE_BELOW_BASELINE

        unique_notes = []
        for col in columns:
            if col.note and col.note not in unique_notes:
                unique_notes.append(col.note)

        if unique_notes:
            max_w = sc.CONTENT_WIDTH - (2 * sc.FOOTNOTE_MARK_RADIUS + 2.2)
            total_lines = sum(len(self._wrap_footnote(n, max_w))
                              for n in unique_notes)
            min_fy = (table_bottom - 9.5) - (total_lines - 1) * 8.0
            actual_bottom = min_fy - 2.0
        else:
            actual_bottom = table_bottom

        return -actual_bottom

    def render_timetable_page(self, route: RouteDefinition, columns: List[CompiledColumn],
                              station_names: Dict[str, Dict[str, str]], is_continued: bool = False,
                              allow_stacking: bool = True) -> int:
        """Renders a timetable. If there is sufficient space on the current page, stacks
        two timetables vertically. Returns the page number on which this table was rendered."""
        route_title = route.get_title(self.lang)
        shares_title = (
            self.tables_on_page > 0
            and self.current_page_title == route_title
        )
        gap = sc.CONTINUED_TABLE_GAP if shares_title else (
            sc.TABLE_STACK_GAP if self.tables_on_page > 0 else 0.0)
        show_banner = not shares_title
        table_h = self.compute_table_height(
            route, columns, show_banner=show_banner)

        # If a table is already on the page, verify if this table fits as the second or third table
        if self.tables_on_page > 0:
            if not allow_stacking or self.tables_on_page >= 3 or (self.cursor_y - gap - table_h < sc.MARGIN_BOTTOM):
                self._finish_page()
                shares_title = False
                show_banner = True
                gap = 0.0
                table_h = self.compute_table_height(
                    route, columns, show_banner=True)

        top_y = self.cursor_y - gap
        c = self.pdf
        rows = route.station_rows
        x0 = sc.MARGIN_LEFT
        x_right = sc.PAGE_WIDTH - sc.MARGIN_RIGHT
        first_col_x = x0 + sc.STATION_COL_WIDTH
        col_w = sc.TRAIN_COL_PITCH
        fs = sc.TEXT_SIZE

        if show_banner:
            title_text = route_title + \
                (f" {self.t['continued']}" if is_continued else "")
            banner_bottom = self._draw_table_banner(
                route.table_id, title_text, top_y)
        else:
            banner_bottom = top_y

        h_h = self.header_height(columns)
        header_rule_y = banner_bottom - h_h

        baselines, rules = self._row_baselines(rows, header_rule_y)
        table_bottom = (
            baselines[-1] if baselines else header_rule_y) - sc.BLOCK_RULE_BELOW_BASELINE
        if table_bottom < sc.MARGIN_BOTTOM and self.tables_on_page == 0:
            raise ValueError(
                f"Table {route.table_id}: {len(rows)} station rows do not fit on one page")

        # ---- exception columns first (background)
        footnotes: List[Tuple[str, list]] = []
        note_letter: Dict[int, str] = {}
        for n, col in enumerate(columns):
            if not col.note:
                continue
            letter = next(
                (l for l, segs in footnotes if segs == col.note), None)
            if letter is None:
                letter = chr(ord("A") + len(footnotes) % 26)
                footnotes.append((letter, col.note))
            note_letter[n] = letter
            self._draw_exception_frame(first_col_x + n * col_w, col_w, banner_bottom - 7.8,
                                       header_rule_y, table_bottom)

        # ---- column headers
        icon_sz = getattr(sc, "ICON_SIZE", 5.4)
        fn_r = getattr(sc, "FOOTNOTE_MARK_RADIUS", 2.8)
        max_icon_lines = max(
            (sum(1 for line in ICON_LINES if any(
                svc in col.trip.services for svc in line)) for col in columns),
            default=0
        )
        lowest_icon_depth = (21.6 + max_icon_lines * icon_sz +
                             (max_icon_lines - 1) * 1.2) if max_icon_lines > 0 else 20.8
        fn_cy = banner_bottom - (lowest_icon_depth + 1.2 + fn_r)

        for n, col in enumerate(columns):
            trip = col.trip
            cx = first_col_x + n * col_w + col_w / 2
            c.setFillColor(sc.COLOR_TEXT_BLACK)
            dfs = self._fit_font(
                col.days_str, sc.FONT_CONDENSED_BOLD, fs, col_w - 1)
            c.setFont(sc.FONT_CONDENSED_BOLD, dfs)
            c.drawCentredString(cx, banner_bottom - 5.5, col.days_str)

            self._draw_train_label(
                cx, banner_bottom - 13.5, trip.train_type, trip.train_number, col_w - 2.4)

            parts = trip.train_class.value.split()
            cw = sum(c.stringWidth(p_, sc.FONT_CONDENSED, sc.CLASS_SIZE)
                     for p_ in parts) + 2.6 * (len(parts) - 1)
            px = cx - cw / 2
            c.setFont(sc.FONT_CONDENSED, sc.CLASS_SIZE)
            for p_ in parts:
                c.drawString(px, banner_bottom - 20.0, p_)
                px += c.stringWidth(p_, sc.FONT_CONDENSED, sc.CLASS_SIZE) + 2.6

            iy = banner_bottom - 21.6 - icon_sz
            for line in ICON_LINES:
                line = [svc for svc in line if svc in trip.services]
                if not line:
                    continue
                total = sum(icon_width(svc, icon_sz)
                            for svc in line) + 1.3 * (len(line) - 1)
                ix = cx - total / 2
                for svc in line:
                    draw_service_icon(c, svc, ix, iy, icon_sz)
                    ix += icon_width(svc, icon_sz) + 1.3
                iy -= icon_sz + 1.2

            if n in note_letter:
                self._draw_footnote_mark(cx, fn_cy, note_letter[n])

        c.setFillColor(sc.COLOR_TEXT_BLACK)
        c.setFont(sc.FONT_CONDENSED_BOLD, fs)
        c.drawString(x0, header_rule_y + 2.9, self.t["km"])
        c.setStrokeColor(sc.COLOR_GRID_LINE)
        c.setLineWidth(sc.RULE_HEADER)
        c.line(x0, header_rule_y, x_right, header_rule_y)

        # ---- station rows
        for s_idx, row_cfg in enumerate(rows):
            is_conn = row_cfg.is_connection
            color = sc.COLOR_FEEDER_RED if is_conn else sc.COLOR_TEXT_BLACK
            font = sc.FONT_CONDENSED_ITALIC if is_conn else sc.FONT_CONDENSED_BOLD
            y = baselines[s_idx]
            c.setFillColor(color)

            if row_cfg.km is not None:
                c.setFont(font, fs)
                c.drawRightString(x0 + sc.KM_RIGHT, y, str(row_cfg.km))

            code = row_cfg.station_code
            name = row_cfg.display_name_override or station_names.get(
                code, {}).get(self.lang, code)
            name_x = x0 + sc.NAME_X
            max_name_w = first_col_x - sc.DOT_LAST_FROM_COLUMN - 6 - name_x
            nfs = self._fit_font(name, font, fs, max_name_w)
            c.setFont(font, nfs)
            c.drawString(name_x, y, name)

            dots, o_x = self._dot_positions(
                name_x + c.stringWidth(name, font, nfs), first_col_x, row_cfg.is_arrival)
            c.setFont(sc.FONT_BODY, sc.TEXT_SIZE)
            for dx in dots:
                c.drawString(dx, y, ".")
            if row_cfg.is_arrival:
                c.drawString(o_x, y, "o")

            c.setFont(font, fs)
            for n, col in enumerate(columns):
                val = col.times.get(s_idx, "")
                if val and val != "|":
                    if val == ":":
                        c.setFont(sc.FONT_CONDENSED_BOLD, fs + 1.2)
                        c.drawCentredString(
                            first_col_x + n * col_w + col_w / 2, y, ":")
                        c.setFont(font, fs)
                    else:
                        c.drawCentredString(
                            first_col_x + n * col_w + col_w / 2, y, self._display_time(val))

        # ---- continuous pass-through lines
        c.setStrokeColor(sc.COLOR_TEXT_BLACK)
        c.setLineWidth(sc.PASS_LINE_WIDTH)
        for n, col in enumerate(columns):
            passing = [col.times.get(i) == "|" for i in range(len(rows))]
            for i, r in enumerate(rows):
                if r.is_connection and not col.times.get(i):
                    above = next((passing[j] for j in range(
                        i - 1, -1, -1) if not rows[j].is_connection), False)
                    below = next((passing[j] for j in range(
                        i + 1, len(rows)) if not rows[j].is_connection), False)
                    passing[i] = above and below
            cx = first_col_x + n * col_w + col_w / 2
            i = 0
            while i < len(rows):
                if passing[i]:
                    j = i
                    while j + 1 < len(rows) and passing[j + 1]:
                        j += 1
                    c.line(cx, baselines[i] + fs *
                           0.78, cx, baselines[j] - 1.6)
                    i = j + 1
                else:
                    i += 1

        # ---- block rules and table end
        c.setStrokeColor(sc.COLOR_GRID_LINE)
        c.setLineWidth(sc.RULE_BLOCK)
        for ry in rules:
            c.line(x0, ry, x_right, ry)
        c.setLineWidth(sc.RULE_TABLE_END)
        c.line(x0, table_bottom, x_right, table_bottom)

        # ---- footnotes under the table
        top_fy = table_bottom - 9.5
        fx, fy = x0, top_fy
        min_fy = top_fy
        max_w = sc.CONTENT_WIDTH - (2 * sc.FOOTNOTE_MARK_RADIUS + 2.2)
        text_x = fx + 2 * sc.FOOTNOTE_MARK_RADIUS + 2.2

        for letter, segs in footnotes:
            lines = self._wrap_footnote(segs, max_w)
            for line_idx, line in enumerate(lines):
                if line_idx == 0:
                    self._draw_footnote_mark(
                        fx + sc.FOOTNOTE_MARK_RADIUS, fy + 2.1, letter)
                tx = text_x
                c.setFillColor(sc.COLOR_TEXT_BLACK)
                for text, bold in line:
                    font = sc.FONT_CONDENSED_BOLD if bold else sc.FONT_CONDENSED
                    c.setFont(font, fs)
                    c.drawString(tx, fy, text)
                    tx += c.stringWidth(text, font, fs)
                min_fy = min(min_fy, fy)
                fy -= 8.0

        if not columns:
            c.setFillColor(sc.COLOR_TEXT_BLACK)
            c.setFont(sc.FONT_CONDENSED_ITALIC, 9)
            c.drawString(first_col_x + 8, header_rule_y +
                         20, self.t["no_trains"])

        # Calculate lower extent and advance state
        actual_bottom = (min_fy - 2.0) if footnotes else table_bottom
        self.tables_on_page += 1
        self.current_page_title = route_title
        self.cursor_y = actual_bottom
        rendered_page = self.current_page_num

        # Finish page if stacking was not requested or page has reached 3 tables
        if not allow_stacking or self.tables_on_page >= 3:
            self._finish_page()

        return rendered_page

    # ---------------------------------------------------------------- station index
    def _index_geometry(self):
        gap = 14.0
        col_w = (sc.CONTENT_WIDTH - gap *
                 (self.INDEX_COLS - 1)) / self.INDEX_COLS
        top = sc.PAGE_HEIGHT - sc.MARGIN_TOP - 30 - 3.5 - 30
        lines_per_col = max(
            3, int((top - sc.MARGIN_BOTTOM - 4) / sc.INDEX_ROW_PITCH) + 1)
        return gap, col_w, top, lines_per_col

    def _layout_index(self, names: List[str]) -> List[List[List[Tuple[str, str]]]]:
        _, _, _, per_col = self._index_geometry()
        items: List[Tuple[str, str]] = []
        last_letter = None
        for name in sorted(names, key=station_sort_key):
            letter = name[:1].upper()
            if letter != last_letter:
                items.append(("bar", letter))
                last_letter = letter
            items.append(("entry", name))
        cols: List[List[Tuple[str, str]]] = []
        cur: List[Tuple[str, str]] = []
        for k, it in enumerate(items):
            if it[0] == "bar" and len(cur) >= per_col - 1:
                cols.append(cur)
                cur = []
            if len(cur) >= per_col:
                cols.append(cur)
                cur = []
            cur.append(it)
        if cur:
            cols.append(cur)
        return [cols[i:i + self.INDEX_COLS] for i in range(0, len(cols), self.INDEX_COLS)] or [[]]

    def index_pages_needed(self, names) -> int:
        if isinstance(names, int):
            names = [f"A{i:05d}" for i in range(names)]
        return len(self._layout_index(list(names)))

    def render_station_index(self, station_to_tables: Dict[str, List[str]]):
        self.flush_page()
        c = self.pdf
        gap, col_w, top, _ = self._index_geometry()
        pages = self._layout_index(list(station_to_tables))
        for page_no, cols in enumerate(pages):
            title = self.t["station_index_title"] + \
                (f" {self.t['continued']}" if page_no else "")
            rule_y = self._draw_page_heading(title)
            c.setFillColor(sc.COLOR_TEXT_BLACK)
            c.setFont(sc.FONT_BODY, sc.TOC_SIZE)
            c.drawString(sc.MARGIN_LEFT, rule_y - 12,
                         self.t["station_index_subtitle"])
            for ci, lines in enumerate(cols):
                x = sc.MARGIN_LEFT + ci * (col_w + gap)
                y = top
                for kind, val in lines:
                    if kind == "bar":
                        c.setFillColor(sc.COLOR_BANNER_BG)
                        c.rect(x, y - 1.9, col_w, sc.INDEX_ROW_PITCH,
                               fill=True, stroke=False)
                        c.setFillColor(sc.COLOR_TEXT_BLACK)
                        c.setFont(sc.FONT_BODY_BOLD, sc.INDEX_SIZE)
                        c.drawString(x + 2, y, val)
                    else:
                        c.setFillColor(sc.COLOR_TEXT_BLACK)
                        c.setFont(sc.FONT_BODY, sc.INDEX_SIZE)
                        c.drawString(x, y, val)
                        c.drawRightString(
                            x + col_w, y, self._compress_ranges(station_to_tables[val]))
                    y -= sc.INDEX_ROW_PITCH
            self._finish_page()

    # ---------------------------------------------------------------- notes
    def render_notes_page(self):
        """Renders a blank ruled page for notes with the standard heading."""
        self.flush_page()
        c = self.pdf
        rule_y = self._draw_page_heading(self.t["notes_title"])

        pitch = getattr(sc, "NOTES_LINE_PITCH", 19.0)
        line_w = getattr(sc, "NOTES_LINE_WIDTH", 0.5)
        line_color = getattr(sc, "COLOR_GRID_LINE", sc.COLOR_TEXT_BLACK)
        gap_top = getattr(sc, "NOTES_GAP_TOP", 19.0)
        bottom_limit = sc.MARGIN_BOTTOM + \
            getattr(sc, "NOTES_MARGIN_BOTTOM", 8.0)

        x0 = sc.MARGIN_LEFT
        x1 = sc.PAGE_WIDTH - sc.MARGIN_RIGHT

        c.saveState()
        c.setStrokeColor(line_color)
        c.setLineWidth(line_w)

        y = rule_y - gap_top
        while y >= bottom_limit:
            c.line(x0, y, x1, y)
            y -= pitch

        c.restoreState()
        self._finish_page(numbered=True)

    @staticmethod
    def _compress_ranges(items: List[str]) -> str:
        num_vals = sorted({int(x) for x in items if x.isdigit()})
        alpha_vals = sorted({x for x in items if not x.isdigit()})
        ranges = []
        if num_vals:
            start = end = num_vals[0]
            for n in num_vals[1:]:
                if n == end + 1:
                    end = n
                else:
                    ranges.append(f"{start}-{end}" if start !=
                                  end else f"{start}")
                    start = end = n
            ranges.append(f"{start}-{end}" if start != end else f"{start}")
        ranges.extend(alpha_vals)
        return ", ".join(ranges)
