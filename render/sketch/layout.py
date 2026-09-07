"""Spalten-/Seiten-Balancer fuer das Sketch-Lernblatt.

Heuristik, keine echte Textmess-Engine: schaetzt pro Block eine Hoehe in "mm-aequivalenten"
Einheiten und verteilt Bloecke sequenziell in Lesereihenfolge auf 3 Spalten je Seite. Dient nur
noch als FALLBACK, wenn keine echten Playwright-Messungen verfuegbar sind (siehe measure.py) --
`layout_pages()` nimmt optional eine Hoehen-Liste entgegen, die diese Schaetzung ersetzt.

Die Konstanten sind aus einem echten Kapitel-Testlauf kalibriert (CALIBRATION_FACTOR) und
bewusst zentral gehalten, damit sie bei Bedarf weiter nachjustiert werden koennen.
"""

CHARS_PER_LINE = 60
MM_PER_LINE = 3.8

# Aus einem echten Kapitel-Testlauf: die Rohschaetzung unten lag bei ~1.8x der tatsaechlich
# gerenderten Hoehe (Spalten endeten bei ~55% Fuellung trotz "vollem" Budget). Ein Faktor,
# nicht einzeln nachjustierte Konstanten -- einfacher erneut zu kalibrieren.
CALIBRATION_FACTOR = 0.6

# A3-Seite (297mm hoch) minus Kopfbereich (Kicker+Titel+Sticky) minus .page-Padding (8+11mm).
PAGE_HEIGHT_MM = 297
PAGE_HEADER_MM = 34
PAGE_PADDING_MM = 19
# Grobe ANNAHME als Fallback, nur falls Playwright fehlt -- normalerweise wird die echte
# Fussleisten-Hoehe gemessen (measure.py: measure_footer_height_mm()) und an layout_pages()
# durchgereicht, siehe render_sketch(). Eine feste Konstante hier fuehrte bei einem langen
# Glossar zu abgeschnittenem Text (die Fussleiste wurde dann groesser als die Reserve).
FOOTER_RESERVE_MM = 46

# Spaltenbreite (420mm Seitenbreite minus 2x9mm Seiten-Padding minus 2x6mm Grid-Gap, durch 3) --
# fuer die Playwright-Realmessung (measure.py), damit dort exakt so umgebrochen wird wie im
# fertigen Lernblatt.
PAGE_WIDTH_MM = 420
PAGE_SIDE_PADDING_MM = 9
COLUMN_GAP_MM = 6
COLUMN_WIDTH_MM = (PAGE_WIDTH_MM - 2 * PAGE_SIDE_PADDING_MM - 2 * COLUMN_GAP_MM) / 3
FOOTER_WIDTH_MM = PAGE_WIDTH_MM - 2 * PAGE_SIDE_PADDING_MM

FULL_COLUMN_BUDGET_MM = PAGE_HEIGHT_MM - PAGE_HEADER_MM - PAGE_PADDING_MM
BLOCK_GAP_MM = 2  # .col{gap:2mm} -- zaehlt zwischen Bloecken, siehe _flow_into_pages()
ORPHAN_HEADING_THRESHOLD_MM = 24

# Feste Basis-Hoehen je Sketch-Template (mm-Aequivalent bei typischer Spaltenbreite).
SKETCH_BASE_HEIGHT_MM = {
    "cycle": 34,
    "rings": 40,
    "triangle": 40,
    "timeline": 22,
    "image": 55,
}
# Templates, deren Hoehe mit der Item-Anzahl skaliert (Basis + Inkrement pro Item).
SKETCH_SCALING_HEIGHT_MM = {
    "stack": (10, 11),   # (Basis, mm pro Item)
    "layers": (6, 9),
    "flow": (10, 2),
}


def _line_count(text: str) -> int:
    length = len(text or "")
    return max(1, -(-length // CHARS_PER_LINE))  # ceil division


def estimate_block_height_mm(block: dict) -> float:
    """Grobe Hoehen-Heuristik (Fallback ohne Playwright) -- CALIBRATION_FACTOR skaliert das
    Rohergebnis auf die empirisch gemessene tatsaechliche Groessenordnung."""
    return _raw_estimate_mm(block) * CALIBRATION_FACTOR


def _raw_estimate_mm(block: dict) -> float:
    btype = block.get("type")
    if btype in ("h2", "h3"):
        return 6.5
    if btype == "def":
        term = block.get("term", "")
        text = block.get("text", "")
        return 4.5 + _line_count(f"{term} {text}") * MM_PER_LINE
    if btype in ("bullets", "arrowlist"):
        items = block.get("items") or []
        return sum(3.2 + _line_count(item) * MM_PER_LINE * 0.55 for item in items) + 1.5
    if btype == "vs":
        left_text = block.get("left", {}).get("text", "")
        right_text = block.get("right", {}).get("text", "")
        longest = max(_line_count(left_text), _line_count(right_text))
        return 6 + longest * MM_PER_LINE * 0.6
    if btype == "box":
        return 9.5 + _line_count(block.get("text", "")) * MM_PER_LINE
    if btype == "note":
        return 4 + _line_count(block.get("text", "")) * MM_PER_LINE * 0.7
    if btype == "table":
        rows = block.get("rows") or []
        return 6 + len(rows) * 4.5
    if btype == "sketch":
        template = block.get("template", "image")
        if template in SKETCH_SCALING_HEIGHT_MM:
            base, per_item = SKETCH_SCALING_HEIGHT_MM[template]
            n = max(len(block.get("items") or []), 1)
            return base + n * per_item
        return SKETCH_BASE_HEIGHT_MM.get(template, 40)
    # merkliste/glossar werden separat als Fussleiste behandelt, nicht im Spaltenfluss.
    return 5.0


def _flow_into_pages(flow_blocks: list, heights_by_id: dict, budget: float) -> list:
    """Verteilt Bloecke sequenziell auf 3-Spalten-Seiten mit dem gegebenen Hoehen-Budget je
    Spalte. Eine h2/h3-Ueberschrift wird nie zum letzten Block einer Spalte -- landet sie im
    letzten ORPHAN_HEADING_THRESHOLD_MM-Rest, wandert sie (mitsamt allem Folgenden) in die
    naechste Spalte bzw. -- am Spaltenende der Seite -- auf eine neue Seite.
    """
    pages = []
    current_page = [[], [], []]
    col_heights = [0.0, 0.0, 0.0]
    col_idx = 0

    def advance_column():
        nonlocal current_page, col_heights, col_idx
        col_idx += 1
        if col_idx > 2:
            pages.append(current_page)
            current_page = [[], [], []]
            col_heights = [0.0, 0.0, 0.0]
            col_idx = 0

    for block in flow_blocks:
        height = heights_by_id[id(block)]
        is_heading = block.get("type") in ("h2", "h3")
        # .col ist ein Flex-Column-Container (gap:2mm) -- der Gap zaehlt nur ZWISCHEN
        # Bloecken, nicht vor dem ersten Block einer (noch leeren) Spalte.
        gap = BLOCK_GAP_MM if col_heights[col_idx] > 0 else 0.0
        remaining = budget - col_heights[col_idx]

        if col_heights[col_idx] > 0 and is_heading and remaining < ORPHAN_HEADING_THRESHOLD_MM:
            advance_column()
            gap = 0.0
        elif col_heights[col_idx] > 0 and col_heights[col_idx] + gap + height > budget:
            advance_column()
            gap = 0.0

        current_page[col_idx].append(block)
        col_heights[col_idx] += gap + height

    pages.append(current_page)
    return pages


def layout_pages(blocks: list, heights: list = None, footer_reserve_mm: float = FOOTER_RESERVE_MM) -> list:
    """Verteilt Bloecke (ohne merkliste/glossar) auf Seiten x 3 Spalten.

    `heights`, falls gegeben, ist eine Liste ECHTER gemessener Hoehen (mm) in derselben
    Reihenfolge wie die Bloecke (siehe measure.py) -- pixelgenau statt geschaetzt. Ohne
    `heights` faellt es auf die estimate_block_height_mm()-Heuristik zurueck.

    `footer_reserve_mm` sollte die ECHTE gemessene Hoehe der Merkliste/Glossar-Fussleiste sein
    (measure.py: measure_footer_height_mm()) -- der Default ist nur eine grobe Annahme fuer
    den Fall ohne Playwright. Eine zu klein angenommene Reserve fuehrt sonst zu abgeschnittenem
    Text am Seitenende (die Fussleiste ist dann in Wirklichkeit hoeher als eingeplant).

    Zwei-Pass-Heuristik fuer die Fussleiste: zuerst mit dem VOLLEN Spaltenbudget probieren
    (maximale Fuellung), denn die Merkliste/Glossar-Fussleiste braucht nur auf der
    tatsaechlich letzten Seite Platz. Reicht der Platz auf der so ermittelten letzten Seite
    dafuer nicht, wird stattdessen mit dem um `footer_reserve_mm` reduzierten Budget neu
    geflossen, das auf jeder Seite von vornherein Reserve laesst -- garantiert genug Platz auf
    der letzten Seite, weil deren hoechste Spalte dann hoechstens
    `FULL_COLUMN_BUDGET_MM - footer_reserve_mm` hoch ist.

    Rueckgabe: Liste von Seiten, jede Seite eine Liste von genau 3 Spalten
    (jede Spalte eine Liste von Bloecken in Lesereihenfolge).
    """
    flow_blocks = [b for b in blocks if b.get("type") not in ("merkliste", "glossar")]
    if not flow_blocks:
        return [[[], [], []]]

    if heights is None:
        heights = [estimate_block_height_mm(b) for b in flow_blocks]
    heights_by_id = {id(b): h for b, h in zip(flow_blocks, heights)}

    if footer_reserve_mm >= FULL_COLUMN_BUDGET_MM:
        # Extremfall: die Fussleiste allein ist schon so hoch wie eine ganze leere Seite (sehr
        # langes Glossar). Kein Spaltenbudget kann ihr dann noch genug Platz NEBEN Inhalt
        # freihalten -- sie bekommt stattdessen eine eigene, sonst leere letzte Seite mit dem
        # vollen Budget. Reicht selbst das nicht, laeuft sie ueber (kein Blocktyp wird ohne
        # echte Text-Paginierung ueber mehrere Seiten aufgeteilt).
        pages = _flow_into_pages(flow_blocks, heights_by_id, FULL_COLUMN_BUDGET_MM)
        pages.append([[], [], []])
        return pages

    pages = _flow_into_pages(flow_blocks, heights_by_id, FULL_COLUMN_BUDGET_MM)
    last_page_max_height = max(column_height_mm(column, heights_by_id) for column in pages[-1])
    if FULL_COLUMN_BUDGET_MM - last_page_max_height < footer_reserve_mm:
        reduced_budget = FULL_COLUMN_BUDGET_MM - footer_reserve_mm
        pages = _flow_into_pages(flow_blocks, heights_by_id, reduced_budget)
    return pages


def column_height_mm(column: list, heights_by_id: dict) -> float:
    """Gesamthoehe einer Spalte inkl. der .col{gap:2mm}-Zwischenraeume (n-1 Gaps bei n
    Bloecken) -- fuer den last_page_sparse-Check in render_sketch()."""
    if not column:
        return 0.0
    return sum(heights_by_id[id(b)] for b in column) + BLOCK_GAP_MM * (len(column) - 1)


def extract_footer_blocks(blocks: list):
    """Gibt (merkliste_block, glossar_block) zurueck -- werden nie in den Spaltenfluss
    aufgenommen, sondern als Fussleiste der letzten Seite gerendert."""
    merkliste = next((b for b in blocks if b.get("type") == "merkliste"), None)
    glossar = next((b for b in blocks if b.get("type") == "glossar"), None)
    return merkliste, glossar
