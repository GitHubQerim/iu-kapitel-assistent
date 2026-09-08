"""Rendert die validierte Sketch-Lernblatt-JSON-Antwort zu einer eigenstaendigen,
offline-faehigen HTML-Datei (A3 quer, 3 Spalten, Handschrift-Look).

Layout/Spaltenverteilung kommt aus layout.py, die SVG-Skizzen aus svg_templates.py -- die KI
liefert nur strukturierten Inhalt (siehe schema/sketch_summary.schema.json), das Aussehen ist
komplett deterministischer Code.
"""
import traceback
from functools import lru_cache
from pathlib import Path

import jinja2

from . import fonts, svg_templates
from .layout import (
    FOOTER_RESERVE_MM,
    FULL_COLUMN_BUDGET_MM,
    column_height_mm,
    estimate_block_height_mm,
    extract_footer_blocks,
    layout_pages,
)

_TEMPLATE_DIR = Path(__file__).parent
_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html", "j2"]),
)


@lru_cache(maxsize=1)
def _read_sketch_css() -> str:
    return (_TEMPLATE_DIR / "sketch.css").read_text(encoding="utf-8")


def render_sketch(data: dict, out_html: Path, image_resolver=None):
    """Baut die Lernblatt-HTML aus der validierten Sketch-JSON-Antwort.

    image_resolver(caption: str) -> str | None: liefert den (relativen) Bildpfad fuer
    sketch-Bloecke vom Typ "image", gematcht ueber die Bildunterschrift (siehe
    kapitel_assistent.caption_key()/caption_text_key()). None -> Platzhalter im Output. Hat
    der Resolver ein get_leftover_images()-Attribut (siehe
    kapitel_assistent.make_sketch_image_resolver()), werden damit nicht referenzierte Bilder
    als eigener Abschnitt "Weitere Abbildungen" ergaenzt statt verworfen.

    Rueckgabe: (out_html_path, warning) -- `warning` ist None im Normalfall, sonst ein
    String mit einer oder mehreren der folgenden Ursachen:
    - die echte Playwright-Messung ist komplett fehlgeschlagen (kein Playwright/Chromium) und
      die grobe Hoehen-Heuristik in layout.py wurde fuer ALLE Bloecke genutzt;
    - einzelne Bloecke liessen sich auch bei Einzelmessung nicht sauber messen und wurden nur
      per Heuristik geschaetzt (siehe measure.py: _measure_blocks());
    - eine oder mehrere Nicht-letzte Seiten nutzen deutlich weniger als ihr Spaltenbudget --
      ein Anzeichen fuer zu grosse Hoehen-Schaetzungen, die den Balancer zu frueh auf eine neue
      Seite wechseln lassen (siehe layout.py: _flow_into_pages()).
    Frueher wurde das alles lautlos verschluckt, wodurch sowohl Layout-Ueberlappungen als auch
    stark unterfuellte Seiten unbemerkt blieben.
    """
    blocks = data.get("blocks", [])
    for block in blocks:
        if block.get("type") == "sketch":
            block["_rendered_html"] = svg_templates.render(block, image_resolver)

    # Bilder, die die KI in keinem "sketch"-Block referenziert hat, nicht stillschweigend
    # verwerfen -- als eigenen Abschnitt vor merkliste/glossar einfuegen (analog zum
    # "Weitere Bilder"-Fallback im normalen Zusammenfassungs-Modus, siehe
    # kapitel_assistent.place_images_inline()).
    get_leftover = getattr(image_resolver, "get_leftover_images", None)
    if callable(get_leftover):
        leftover_entries = get_leftover()
        if leftover_entries:
            out_dir = Path(out_html).parent
            leftover_blocks = [{"type": "h2", "text": "Weitere Abbildungen aus diesem Kapitel"}]
            for pdf_path, page_num, img_path, caption in leftover_entries:
                label = caption or f"{pdf_path.stem} Seite {page_num}"
                rel_path = str(img_path.relative_to(out_dir))
                img_block = {"type": "sketch", "template": "image", "caption": label}
                img_block["_rendered_html"] = svg_templates.render_image(img_block, rel_path)
                leftover_blocks.append(img_block)
            # merkliste/glossar muessen laut extract_footer_blocks()/render_footer() am ENDE
            # des blocks-Arrays stehen -- die neuen Bloecke davor einfuegen.
            insert_at = next(
                (i for i, b in enumerate(blocks) if b.get("type") in ("merkliste", "glossar")),
                len(blocks),
            )
            blocks[insert_at:insert_at] = leftover_blocks

    font_face_css = fonts.build_font_face_css()
    sketch_css = _read_sketch_css()
    merkliste, glossar = extract_footer_blocks(blocks)

    flow_blocks = [b for b in blocks if b.get("type") not in ("merkliste", "glossar")]
    heights = None
    footer_reserve_mm = FOOTER_RESERVE_MM
    warnings = []
    try:
        from .measure import measure_layout_mm
        heights, measured_footer_mm, failed_blocks = measure_layout_mm(
            flow_blocks, merkliste, glossar, sketch_css, font_face_css,
        )
        if merkliste or glossar:
            footer_reserve_mm = measured_footer_mm
        if failed_blocks:
            # Nur einzelne Bloecke waren nicht sauber messbar (siehe measure.py) -- der Rest
            # des Kapitels nutzt weiterhin echte Messwerte, trotzdem sichtbar machen.
            details = ", ".join(f"#{i} ({t})" for i, t, _ in failed_blocks)
            warnings.append(
                f"{len(failed_blocks)} Block/Bloecke konnten nicht einzeln vermessen werden "
                f"und wurden per Heuristik geschaetzt: {details}."
            )
    except Exception as exc:
        # Kein playwright, playwright install chromium fehlt, oder der Browser startet
        # grundsaetzlich nicht -- Heuristik in layout.py greift automatisch
        # (layout_pages(blocks, heights=None)), footer_reserve_mm bleibt die grobe
        # FOOTER_RESERVE_MM-Annahme.
        heights = None
        warnings.append(
            "Konnte Block-Hoehen nicht echt vermessen (Playwright/Chromium-Fehler), "
            f"nutze die grobe Schaetz-Heuristik fuer ALLE Bloecke: {exc!r}. "
            "Layout kann dadurch ungenauer sein (z. B. Ueberlauf bei sehr langen Tabellen "
            "oder stark unterfuellte Seiten). Details:\n" + traceback.format_exc()
        )
    heights_by_id = (
        {id(b): h for b, h in zip(flow_blocks, heights)} if heights is not None
        else {id(b): estimate_block_height_mm(b) for b in flow_blocks}
    )

    pages = layout_pages(blocks, heights=heights, footer_reserve_mm=footer_reserve_mm)

    # Ist die letzte Seite deutlich unterfuellt (duennes KI-JSON, nicht Balancer-Schuld),
    # bleibt die Merkliste/Glossar-Fussleiste sonst weit unter dem Spalteninhalt am reinen
    # Seitenfuss haengen (.grid hat flex:1 und streckt sich immer auf volle Hoehe). Dann die
    # Fussleiste stattdessen direkt unter die Spalten setzen (page.compact -> .grid{flex:none}).
    last_page_max_height = max(column_height_mm(column, heights_by_id) for column in pages[-1])
    last_page_sparse = last_page_max_height < FULL_COLUMN_BUDGET_MM * 0.8

    # Regressions-Wache: eine NICHT-letzte Seite, die deutlich weniger als ihr Spaltenbudget
    # nutzt, ist (anders als bei der letzten Seite) immer ein Zeichen fuer zu grob geschaetzte
    # Bloeckhoehen, die den Balancer zu frueh auf eine neue Seite wechseln lassen -- das genaue
    # Muster, das zu den stark unterfuellten Kapiteln gefuehrt hat (siehe Session-Historie).
    underfilled_pages = [
        i + 1 for i, page in enumerate(pages[:-1])
        if max(column_height_mm(col, heights_by_id) for col in page) < FULL_COLUMN_BUDGET_MM * 0.6
    ]
    if underfilled_pages:
        warnings.append(
            f"Seite(n) {underfilled_pages} nutzen weniger als 60% des Spaltenbudgets, obwohl "
            "sie nicht die letzte Seite sind -- Layout wahrscheinlich unterfuellt "
            "(Hoehen-Schaetzung vermutlich zu grosszuegig, siehe layout.py)."
        )

    warning = "\n".join(warnings) if warnings else None

    template = _ENV.get_template("template.html.j2")
    html_out = template.render(
        module=data.get("module", ""),
        chapter=data.get("chapter", {}),
        learning_goals=data.get("learning_goals", []),
        pages=pages,
        merkliste=merkliste,
        glossar=glossar,
        last_page_sparse=last_page_sparse,
        font_face_css=font_face_css,
        sketch_css=sketch_css,
    )

    out_html = Path(out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html_out, encoding="utf-8")
    return out_html, warning


def render_sketch_pdf(out_html: Path):
    """Optionaler PDF-Export via Playwright (A3 quer). Gibt den PDF-Pfad zurueck, oder None
    plus Hinweistext, falls playwright fehlt oder der Export fehlschlaegt (z.B. weil
    `playwright install chromium` noch nicht gelaufen ist) -- die HTML-Datei existiert in
    beiden Faellen bereits und geht nicht verloren."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "playwright nicht installiert — im Browser Cmd+P → Als PDF sichern."

    out_html = Path(out_html)
    pdf_path = out_html.with_suffix(".pdf")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(out_html.resolve().as_uri())
            page.pdf(
                path=str(pdf_path),
                format="A3",
                landscape=True,
                print_background=True,
                prefer_css_page_size=True,
            )
            browser.close()
    except Exception as exc:
        return None, (
            f"PDF-Export fehlgeschlagen ({exc}) — vermutlich fehlt `playwright install "
            "chromium`. Im Browser Cmd+P → Als PDF sichern."
        )
    return pdf_path, None
