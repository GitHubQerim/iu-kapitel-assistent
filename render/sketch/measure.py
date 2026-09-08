"""Misst echte Block- und Fussleisten-Hoehen im Headless-Browser (Playwright) statt sie zu
schaetzen.

Rendert Bloecke in einen Flex-Column-Container mit exakt der echten Spaltenbreite
(COLUMN_WIDTH_MM) bzw. die Merkliste/Glossar-Fussleiste in voller Seitenbreite
(FOOTER_WIDTH_MM) -- derselbe Kontext wie im fertigen Lernblatt, keine Margin-Collapse,
gleiche Fonts/CSS -- und liest `getBoundingClientRect().height` aus. Optional: wenn Playwright
fehlt, faellt render_sketch() komplett auf die Heuristik in layout.py zurueck (siehe dortige
Docstrings). Scheitert nur die BATCH-Messung (z.B. weil ein einzelner Block zu != 1
Top-Level-Element rendert), wird NICHT das gesamte Kapitel auf die Heuristik zurueckgeworfen --
stattdessen misst _measure_blocks() jeden Block einzeln nach und schaetzt nur die tatsaechlich
defekten Bloecke (siehe failed_blocks im Rueckgabewert)."""
from pathlib import Path

import jinja2

from .layout import COLUMN_WIDTH_MM, FOOTER_WIDTH_MM, estimate_block_height_mm

_TEMPLATE_DIR = Path(__file__).parent
_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html", "j2"]),
)
_MM_PER_PX = 25.4 / 96


def _measure_blocks(browser, block_template, blocks, sketch_css, font_face_css):
    """Misst alle Bloecke in EINEM Browser-Tab (schnell). Gibt (heights_mm, failed_blocks)
    zurueck -- failed_blocks ist eine Liste von (index, block_type, error_repr) fuer Bloecke,
    die auch bei Einzelmessung nicht sauber zu genau 1 Element gerendert haben (fuer die
    dann estimate_block_height_mm() als Schaetzung einspringt)."""
    if not blocks:
        return [], []

    html = block_template.render(
        blocks=blocks, sketch_css=sketch_css, font_face_css=font_face_css,
        column_width_mm=COLUMN_WIDTH_MM,
    )
    page = browser.new_page()
    try:
        page.set_content(html)
        heights_px = page.eval_on_selector_all(
            ".measure-col > *", "els => els.map(e => e.getBoundingClientRect().height)"
        )
    finally:
        page.close()

    if len(heights_px) == len(blocks):
        return [h * _MM_PER_PX for h in heights_px], []

    # Batch-Messung inkonsistent (irgendein Block rendert zu != 1 Element, z.B. leeres
    # "items"-Array oder eine unerwartete Block-Kombination) -- jeden Block EINZELN messen,
    # damit nur der/die tatsaechlich defekten Bloecke geschaetzt werden muessen statt ALLER.
    heights_mm = []
    failed_blocks = []
    for i, block in enumerate(blocks):
        try:
            single_html = block_template.render(
                blocks=[block], sketch_css=sketch_css, font_face_css=font_face_css,
                column_width_mm=COLUMN_WIDTH_MM,
            )
            page = browser.new_page()
            try:
                page.set_content(single_html)
                px = page.eval_on_selector_all(
                    ".measure-col > *", "els => els.map(e => e.getBoundingClientRect().height)"
                )
            finally:
                page.close()
            if len(px) != 1:
                raise RuntimeError(
                    f"Block rendert zu {len(px)} Top-Level-Elementen statt 1 "
                    f"(type={block.get('type')!r})"
                )
            heights_mm.append(px[0] * _MM_PER_PX)
        except Exception as exc:
            heights_mm.append(estimate_block_height_mm(block))
            failed_blocks.append((i, block.get("type"), repr(exc)))
    return heights_mm, failed_blocks


def measure_layout_mm(blocks: list, merkliste, glossar, sketch_css: str, font_face_css: str):
    """Misst Block-Hoehen UND Fussleisten-Hoehe in einem Browser-Start.

    Gibt (block_heights_mm, footer_height_mm, failed_blocks) zurueck -- block_heights_mm in
    derselben Reihenfolge wie `blocks`, footer_height_mm ist 0.0 wenn weder merkliste noch
    glossar gesetzt sind, failed_blocks eine (moeglicherweise leere) Liste von
    (index, block_type, error_repr) fuer Bloecke, die per Heuristik statt echter Messung
    geschaetzt wurden (siehe _measure_blocks()).

    Wirft ImportError (kein playwright) oder jede andere Exception, die beim Rendern/Messen
    grundsaetzlich auftritt (z.B. `playwright install chromium` nicht gelaufen, Browser startet
    nicht) -- der Aufrufer faengt DAS ab und nutzt dann die Heuristik fuer ALLE Bloecke. Ein
    einzelner defekter Block fuehrt NICHT mehr zu dieser komplett-Fallback-Exception (siehe
    _measure_blocks()).
    """
    from playwright.sync_api import sync_playwright

    block_template = _ENV.get_template("measure.html.j2")

    footer_html = None
    if merkliste or glossar:
        footer_template = _ENV.get_template("measure_footer.html.j2")
        footer_html = footer_template.render(
            merkliste=merkliste, glossar=glossar, sketch_css=sketch_css,
            font_face_css=font_face_css, footer_width_mm=FOOTER_WIDTH_MM,
        )

    with sync_playwright() as p:
        browser = p.chromium.launch()

        block_heights_mm, failed_blocks = _measure_blocks(
            browser, block_template, blocks, sketch_css, font_face_css,
        )

        footer_height_px = 0.0
        if footer_html is not None:
            page = browser.new_page()
            page.set_content(footer_html)
            footer_height_px = page.eval_on_selector(
                ".measure-footer", "el => el.getBoundingClientRect().height"
            )
            page.close()

        browser.close()

    footer_height_mm = footer_height_px * _MM_PER_PX
    return block_heights_mm, footer_height_mm, failed_blocks
