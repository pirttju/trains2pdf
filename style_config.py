"""
style_config.py - Page geometry (23.21 x 17.46 cm), colors, fonts, and dimensions.

All sizes below were measured from the printed VR 2007 timetable booklet (a spread of
665 x 493 pt, practically the same size as this page) so that type, row spacing, dot
leaders and rules come out at the same scale.
"""
import os
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

PAGE_WIDTH = 12.5 * cm
PAGE_HEIGHT = 17.6 * cm

# Margins (booklet: content starts 22.5 pt from the edge, banner top 17.3 pt from the top)
MARGIN_LEFT = 22.5
MARGIN_RIGHT = 22.5
MARGIN_TOP = 17.3
MARGIN_BOTTOM = 28.0

CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
CONTENT_HEIGHT = PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

# ---------------------------------------------------------------- cover page
COVER_IMAGE_PATH = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "images", "cover.jpg")
COLOR_COVER_TITLE_BG = HexColor("#ED1C24")
COLOR_COVER_TITLE = HexColor("#FFFFFF")
COLOR_COVER_SUBTITLE = HexColor("#221F1F")
COVER_PADDING_X = 19.0
COVER_PADDING_Y = 9.5
TITLE_FONT_SIZE = 19.0
SUBTITLE_FONT_SIZE = 13.5

# ---------------------------------------------------------------- map page
MAP_PATH = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "map", "map.svg")
# Padding between page heading rule and black border block
MAP_PADDING_TOP = 5.0
MAP_BORDER_WIDTH = 0.8         # Stroke width of the black border block
MAP_INNER_PADDING = 0.8        # Inset padding between border block and map drawing
MAP_FIT_BORDER_TO_MAP = False  # if True, shrink border block to fit map aspect ratio
MAP_SUBTITLE_SIZE = 8.5        # font size for subtitle
MAP_SUBTITLE_GAP = 5.0         # gap between title and subtitle

# ---------------------------------------------------------------- timetable geometry (pt)
BANNER_HEIGHT = 19.0            # outer frame height
BANNER_OUTER_RULE = 1.066
BANNER_INNER_RULE = 0.533
BANNER_NUMBER_SIZE = 13.5
BANNER_TITLE_SIZE = 9.5

# km + station name + dot leaders, up to the first train column
STATION_COL_WIDTH = 79.6
KM_RIGHT = 12.4                 # km figures right-aligned this far from the margin
NAME_X = 14.5                   # station name starts this far from the margin
TRAIN_COL_PITCH = 22.9          # train column width
HEADER_HEIGHT = 64.5            # banner bottom -> rule above the first station row
ROW_PITCH = 7.03                # baseline to baseline
FIRST_BASELINE_BELOW_RULE = 6.2
# block rule position under the previous row's baseline
BLOCK_RULE_BELOW_BASELINE = 2.4
# next baseline under a block rule (pitch over a rule = 8.1)
BASELINE_BELOW_BLOCK_RULE = 5.7

TEXT_SIZE = 6.3
CLASS_SIZE = 5.3
ICON_SIZE = 6.4

# dot leaders sit on a fixed grid anchored at the right end
DOT_PITCH = 3.99
DOT_GAP_AFTER_NAME = 0.8
# last leader dot this far left of the first train column
DOT_LAST_FROM_COLUMN = 4.6
ARRIVAL_O_AFTER_DOT = 1.8       # arrival rows: '.o' replaces the last dot

RULE_BLOCK = 0.425              # rules between station blocks
RULE_HEADER = 0.533             # rule under the column header
RULE_TABLE_END = 1.066
PASS_LINE_WIDTH = 0.8           # continuous "does not stop" line

PAGE_NUMBER_SIZE = 8.0

# Gap in points between two stacked timetables on the same page
TABLE_STACK_GAP = 14.06
CONTINUED_TABLE_GAP = 3.515

# ---------------------------------------------------------------- other pages (booklet uses Arial)
HEADING_SIZE = 12.0
TOC_SIZE = 8.5
TOC_ROW_PITCH = 13.5
INDEX_SIZE = 7.0
INDEX_ROW_PITCH = 7.8
SYMBOLS_SIZE = 7.0

# ---------------------------------------------------------------- notes page
# Baseline-to-baseline distance between horizontal rules
NOTES_LINE_PITCH = 19.0
NOTES_LINE_WIDTH = 0.5          # Stroke width of the rules
NOTES_GAP_TOP = 19.0            # Spacing between the heading rule and the first line
NOTES_MARGIN_BOTTOM = 8.0       # Clearance above MARGIN_BOTTOM / page footer

# ---------------------------------------------------------------- colors
COLOR_BANNER_BG = HexColor("#F69679")        # headers
# connection (feeder) rows: true red, not pink
COLOR_FEEDER_RED = HexColor("#ED1C24")
COLOR_GRID_LINE = HexColor("#221F1F")
COLOR_LIGHT_LINE = HexColor("#D0D0D0")
COLOR_TEXT_BLACK = HexColor("#221F1F")
# alternating rows / heading tab (tint of the header colour)
COLOR_TOC_TINT = HexColor("#FCE8F1")
COLOR_WHITE = HexColor("#FFFFFF")
# diagonal stripes behind an exception column's header
COLOR_HATCH = HexColor("#D5D5D5")
# grey frame around an exception column
COLOR_EXCEPTION_OUTLINE = HexColor("#939597")

# ---------------------------------------------------------------- exception columns / icons
HATCH_SPACING = 9.6             # stripe pitch (pt, measured along x)
HATCH_WIDTH = 3.2
EXCEPTION_OUTLINE_WIDTH = 1.0
EXCEPTION_INSET = 1.3           # frame inset from the column edges
TRAIN_TYPE_SIZE = 6.3           # heavy italic train type (S, SP, IC)
STYLED_TRAIN_TYPES = {"S", "SP", "IC"}
# drawn as a graphic badge
BADGE_TRAIN_TYPES = {"IC"}
# Optional user-supplied symbol images (PNG/JPG with transparency), drawn instead of the badge
LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos")
# user symbols are set at the train number's cap height, on the baseline
LOGO_HEIGHT = 4.025
# SVG symbols: every non-white colour is drawn in this colour (None = keep)
LOGO_RECOLOR = "#1A1A1A"
TRAIN_TYPE_LOGO_FILES = {t: [os.path.join(LOGO_DIR, f"{t}.{ext}") for ext in ("svg", "png", "jpg", "jpeg")]
                         for t in ("IC", "S", "SP")}   # first existing file wins (SVG = vector)
BADGE_HEIGHT = 5.4
BADGE_RADIUS = 1.1
BADGE_TEXT_SIZE = 5.2
FOOTNOTE_MARK_RADIUS = 2.8

# ---------------------------------------------------------------- fonts
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_FONTS = {
    "HelveticaNeue-Roman": "Helvetica 55 Roman Regular.ttf",
    "Helvetica75-Bold": "Helvetica75 Bold.ttf",
    "Helvetica57-Condensed": "Helvetica57-Condensed Roman.ttf",
    "Helvetica77-CondensedBold": "Helvetica77-Condensed Bold.ttf",
    "Helvetica77-CondensedBoldObl": "Helvetica77-Condensed BoldItalic.ttf"
}


def _register_fonts() -> bool:
    try:
        for name, fn in _FONTS.items():
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(
                    TTFont(name, os.path.join(_FONT_DIR, fn)))
        return True
    except Exception as exc:  # missing/broken font files
        print(
            f"[WARN] Condensed fonts not available ({exc}); using Helvetica.")
        return False


if _register_fonts():
    FONT_BODY = "HelveticaNeue-Roman"
    FONT_BODY_BOLD = "Helvetica75-Bold"
    FONT_CONDENSED = "Helvetica57-Condensed"
    FONT_CONDENSED_BOLD = "Helvetica77-CondensedBold"
    FONT_CONDENSED_ITALIC = "Helvetica77-CondensedBoldObl"
else:
    FONT_BODY = "Helvetica"
    FONT_BODY_BOLD = "Helvetica-Bold"
    FONT_CONDENSED = "Helvetica"
    FONT_CONDENSED_BOLD = "Helvetica-Bold"
    FONT_CONDENSED_ITALIC = "Helvetica-BoldOblique"
