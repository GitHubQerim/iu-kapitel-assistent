import json
import re
from pathlib import Path

import pytest

from render.sketch import render_sketch
from render.sketch.layout import FULL_COLUMN_BUDGET_MM, estimate_block_height_mm, layout_pages
from render.sketch.svg_templates import TEMPLATES

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lektion1_sketch.json"


@pytest.fixture
def fixture_data():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_render_sketch_attaches_leftover_images(tmp_path):
    """Bilder, die die KI in keinem 'sketch'-Block referenziert hat, muessen als eigener
    Abschnitt angehaengt werden statt zu verschwinden (siehe
    kapitel_assistent.make_sketch_image_resolver()/get_leftover_images())."""
    from kapitel_assistent import make_sketch_image_resolver

    bilder_dir = tmp_path / "bilder"
    bilder_dir.mkdir()
    referenced_img = bilder_dir / "seite1.jpg"
    referenced_img.write_bytes(b"x")
    leftover_img = bilder_dir / "seite2.jpg"
    leftover_img.write_bytes(b"x")

    saved_images = [
        (Path("kapitel.pdf"), 1, referenced_img, "Abbildung 1: Referenziert"),
        (Path("kapitel.pdf"), 2, leftover_img, "Abbildung 2: Nicht referenziert"),
    ]
    resolver = make_sketch_image_resolver(saved_images, tmp_path)

    data = {
        "module": "Testmodul",
        "chapter": {"number": 1, "title": "Test", "pages": "1-2"},
        "learning_goals": ["Ziel eins"],
        "blocks": [
            {"type": "h2", "text": "Abschnitt"},
            {"type": "sketch", "template": "image", "figure": 1, "caption": "Abbildung 1: Referenziert"},
            {"type": "merkliste", "items": ["Kurz"]},
            {"type": "glossar", "items": [{"term": "X", "text": "Y"}]},
        ],
    }
    out, _ = render_sketch(data, tmp_path / "lernblatt.html", image_resolver=resolver)
    html = out.read_text(encoding="utf-8")
    assert "Weitere Abbildungen aus diesem Kapitel" in html
    assert "seite2.jpg" in html
    # das referenzierte Bild darf nicht zusaetzlich im Leftover-Abschnitt auftauchen
    assert html.count("seite1.jpg") == 1


def test_render_sketch_writes_two_pages(tmp_path, fixture_data):
    out, _ = render_sketch(fixture_data, tmp_path / "lernblatt.html")
    html = out.read_text(encoding="utf-8")
    assert len(re.findall(r'<section class="page(?: compact)?">', html)) == 2


def test_render_sketch_covers_all_templates(tmp_path, fixture_data):
    out, _ = render_sketch(fixture_data, tmp_path / "lernblatt.html")
    html = out.read_text(encoding="utf-8")
    found = set(re.findall(r'data-sketch="([a-z]+)"', html))
    assert set(TEMPLATES) <= found


def test_render_sketch_has_footer_strip_only_on_last_page(tmp_path, fixture_data):
    out, _ = render_sketch(fixture_data, tmp_path / "lernblatt.html")
    html = out.read_text(encoding="utf-8")
    assert html.count("Prüfungs-Merkliste in Kürze") == 1
    assert html.count(">Glossar<") == 1


def test_render_sketch_without_image_resolver_shows_placeholder(tmp_path, fixture_data):
    out, _ = render_sketch(fixture_data, tmp_path / "lernblatt.html", image_resolver=None)
    html = out.read_text(encoding="utf-8")
    assert "Bild fehlt" in html


def test_render_sketch_sparse_last_page_gets_compact_class(tmp_path):
    """Duennes JSON (kurzer merkliste/glossar-Block direkt nach wenigen Bloecken) darf die
    Fussleiste nicht weit unterhalb des Spalteninhalts am Seitenfuss haengen lassen."""
    sparse_data = {
        "module": "Testmodul",
        "chapter": {"number": 1, "title": "Test", "pages": "1-2"},
        "learning_goals": ["Ziel eins"],
        "blocks": [
            {"type": "h2", "text": "Kurzer Abschnitt"},
            {"type": "bullets", "items": ["Ein Punkt"]},
            {"type": "merkliste", "items": ["Kurz"]},
            {"type": "glossar", "items": [{"term": "X", "text": "Y"}]},
        ],
    }
    out, _ = render_sketch(sparse_data, tmp_path / "lernblatt.html")
    html = out.read_text(encoding="utf-8")
    assert 'class="page compact"' in html


def test_render_sketch_renders_table_block(tmp_path):
    data = {
        "module": "Testmodul",
        "chapter": {"number": 1, "title": "Test", "pages": "1-2"},
        "learning_goals": ["Ziel eins"],
        "blocks": [
            {"type": "h2", "text": "Betroffenenrechte"},
            {"type": "table", "headers": ["Artikel", "Recht"], "rows": [["Art. 15", "Auskunft"], ["Art. 17", "Löschung"]]},
            {"type": "merkliste", "items": ["Kurz"]},
            {"type": "glossar", "items": [{"term": "X", "text": "Y"}]},
        ],
    }
    out, _ = render_sketch(data, tmp_path / "lernblatt.html")
    html = out.read_text(encoding="utf-8")
    assert "<table class=\"table-block" in html
    assert "Art. 15" in html and "Löschung" in html


def test_render_sketch_falls_back_without_playwright(tmp_path, fixture_data, monkeypatch):
    """measure_block_heights_mm() muss bei fehlendem playwright NICHT crashen -- render_sketch()
    faellt dann auf die estimate_block_height_mm()-Heuristik in layout.py zurueck."""
    import sys

    monkeypatch.setitem(sys.modules, "playwright", None)
    out, _ = render_sketch(fixture_data, tmp_path / "lernblatt.html")
    assert out.exists()


def _sketch_data_with_glossary(n_terms: int, repeat: int = 1) -> dict:
    glossary_items = [
        {"term": f"Begriff {i}", "text": "Eine ziemlich lange Erklärung, die mehrere Wörter braucht " * repeat}
        for i in range(n_terms)
    ]
    return {
        "module": "Testmodul",
        "chapter": {"number": 1, "title": "Test", "pages": "1-2"},
        "learning_goals": ["Ziel eins"],
        "blocks": [
            {"type": "h2", "text": "Abschnitt"},
            {"type": "bullets", "items": ["Ein Punkt"]},
            {"type": "merkliste", "items": ["Merksatz " + str(i) for i in range(10)]},
            {"type": "glossar", "items": glossary_items},
        ],
    }


def _footer_vs_page_bottom_px(playwright_sync_api, out_path):
    with playwright_sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(out_path.resolve().as_uri())
        last_page = page.query_selector_all("section.page")[-1]
        page_box = last_page.bounding_box()
        page_bottom = page_box["y"] + page_box["height"]
        strip = page.query_selector(".bottom-strip")
        strip_box = strip.bounding_box() if strip else None
        n_pages = len(page.query_selector_all("section.page"))
        browser.close()
    strip_bottom = (strip_box["y"] + strip_box["height"]) if strip_box else None
    return strip_bottom, page_bottom, n_pages


def test_render_sketch_large_glossary_does_not_overflow_page(tmp_path):
    """Regression: eine lange Merkliste/Glossar-Fussleiste wurde bisher gegen eine feste
    46mm-Annahme geplant statt gegen ihre echte Hoehe -- bei einem laengeren, aber
    realistischen Glossar lief der Text ueber den Seitenrand hinaus und wurde von
    .page{overflow:hidden} abgeschnitten."""
    playwright_sync_api = pytest.importorskip("playwright.sync_api")

    data = _sketch_data_with_glossary(n_terms=18, repeat=1)
    out, _ = render_sketch(data, tmp_path / "lernblatt.html")
    strip_bottom, page_bottom, _ = _footer_vs_page_bottom_px(playwright_sync_api, out)

    assert strip_bottom <= page_bottom + 1, (
        f"Fussleiste ({strip_bottom:.0f}px) läuft über das Seitenende ({page_bottom:.0f}px) hinaus"
    )


def test_render_sketch_extreme_glossary_gets_dedicated_page(tmp_path):
    """Extremfall: ein Glossar, das allein schon hoeher ist als eine ganze leere Seite, kann
    prinzipbedingt nicht ueberlauffrei neben Spalteninhalt passen (keine echte
    Text-Paginierung). layout_pages() muss ihm dafuer wenigstens eine eigene, sonst leere
    letzte Seite geben -- statt still zusammen mit Spalteninhalt zu ueberlaufen -- und darf
    dabei nicht crashen."""
    playwright_sync_api = pytest.importorskip("playwright.sync_api")

    data = _sketch_data_with_glossary(n_terms=40, repeat=3)
    out, _ = render_sketch(data, tmp_path / "lernblatt.html")
    html = out.read_text(encoding="utf-8")
    assert 'class="page compact"' in html  # eigene Seite, Grid leer -> compact

    _, _, n_pages = _footer_vs_page_bottom_px(playwright_sync_api, out)
    assert n_pages == 2  # 1 Inhaltsseite + 1 dedizierte Fussleisten-Seite


def test_render_sketch_offline_no_external_requests(tmp_path, fixture_data):
    out, _ = render_sketch(fixture_data, tmp_path / "lernblatt.html")
    html = out.read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html
    assert "http://" not in html and "https://" not in html


def test_layout_columns_stay_within_budget(fixture_data):
    """Smoke-Test: die Layout-Heuristik haelt ihr eigenes Budget ein. Das prueft NICHT, ob
    das Budget selbst realistisch kalibriert ist -- das ist die manuelle visuelle Abnahme."""
    flow_blocks = [b for b in fixture_data["blocks"] if b["type"] not in ("merkliste", "glossar")]
    pages = layout_pages(flow_blocks)
    for page in pages:
        for column in page:
            total = sum(estimate_block_height_mm(b) for b in column)
            # Ein einzelner ueberdimensionierter Block darf das Budget ueberschreiten (siehe
            # layout.py), aber eine ganze Spalte sollte nicht grob aus dem Ruder laufen. Die
            # meisten Seiten nutzen das VOLLE Budget (Fussleisten-Reserve nur auf der letzten
            # Seite, siehe layout_pages()).
            assert total <= FULL_COLUMN_BUDGET_MM * 1.15
