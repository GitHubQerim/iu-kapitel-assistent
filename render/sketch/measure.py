"""Misst echte Block- und Fussleisten-Hoehen im Headless-Browser (Playwright) statt sie zu
schaetzen.

Rendert Bloecke in einen Flex-Column-Container mit exakt der echten Spaltenbreite
(COLUMN_WIDTH_MM) bzw. die Merkliste/Glossar-Fussleiste in voller Seitenbreite
(FOOTER_WIDTH_MM) -- derselbe Kontext wie im fertigen Lernblatt, keine Margin-Collapse,
gleiche Fonts/CSS -- und liest `getBoundingClientRect().height` aus. Optional: wenn Playwright
fehlt oder der Messversuch aus irgendeinem Grund scheitert, faellt render_sketch() auf die
Heuristik in layout.py zurueck (siehe dortige Docstrings).
"""
from pathlib import Path

import jinja2

from .layout import COLUMN_WIDTH_MM, FOOTER_WIDTH_MM

_TEMPLATE_DIR = Path(__file__).parent
_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html", "j2"]),
)
_MM_PER_PX = 25.4 / 96


def measure_layout_mm(blocks: list, merkliste, glossar, sketch_css: str, font_face_css: str):
    """Misst Block-Hoehen UND Fussleisten-Hoehe in einem Browser-Start.

    Gibt (block_heights_mm, footer_height_mm) zurueck -- block_heights_mm in derselben
    Reihenfolge wie `blocks`, footer_height_mm ist 0.0 wenn weder merkliste noch glossar
    gesetzt sind.

    Wirft ImportError (kein playwright) oder jede andere Exception, die beim Rendern/Messen
    auftritt (z.B. `playwright install chromium` nicht gelaufen) -- der Aufrufer faengt das ab
    und nutzt dann die Heuristik.
    """
    from playwright.sync_api import sync_playwright

    block_template = _ENV.get_template("measure.html.j2")
    block_html = block_template.render(
        blocks=blocks, sketch_css=sketch_css, font_face_css=font_face_css,
        column_width_mm=COLUMN_WIDTH_MM,
    )

    footer_html = None
    if merkliste or glossar:
        footer_template = _ENV.get_template("measure_footer.html.j2")
        footer_html = footer_template.render(
            merkliste=merkliste, glossar=glossar, sketch_css=sketch_css,
            font_face_css=font_face_css, footer_width_mm=FOOTER_WIDTH_MM,
        )

    with sync_playwright() as p:
        browser = p.chromium.launch()

        block_heights_px = []
        if blocks:
            page = browser.new_page()
            page.set_content(block_html)
            block_heights_px = page.eval_on_selector_all(
                ".measure-col > *", "els => els.map(e => e.getBoundingClientRect().height)"
            )
            page.close()

        footer_height_px = 0.0
        if footer_html is not None:
            page = browser.new_page()
            page.set_content(footer_html)
            footer_height_px = page.eval_on_selector(
                ".measure-footer", "el => el.getBoundingClientRect().height"
            )
            page.close()

        browser.close()

    if len(block_heights_px) != len(blocks):
        raise RuntimeError(
            f"Mess-Mismatch: {len(block_heights_px)} gemessene Elemente fuer {len(blocks)} "
            "Bloecke -- ein Block rendert vermutlich zu != 1 Top-Level-Element."
        )
    block_heights_mm = [h * _MM_PER_PX for h in block_heights_px]
    footer_height_mm = footer_height_px * _MM_PER_PX
    return block_heights_mm, footer_height_mm
