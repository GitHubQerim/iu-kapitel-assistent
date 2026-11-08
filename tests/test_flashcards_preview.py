import kapitel_assistent as ka


def test_render_flashcards_html_prefixes_image_src_with_bilder_dir():
    cards = [
        {"front": "Frage ohne Bild", "back": "Antwort"},
        {"front": "Frage mit Bild", "back": 'Antwort<br><img src="kapitel_1_seite2_I1.jpg">'},
    ]
    out = ka.render_flashcards_html(cards, "Mein Deck", "karteikarten_bilder")

    assert "Mein Deck" in out
    assert "2 Karte(n)" in out
    assert "Frage ohne Bild" in out
    assert '<img src="karteikarten_bilder/kapitel_1_seite2_I1.jpg">' in out
    # das Deck selbst referenziert Bilder flach (ohne Unterordner) -- die Vorschau darf
    # das Original im card["back"] nicht verändern, nur ihre eigene Kopie der HTML
    assert cards[1]["back"] == 'Antwort<br><img src="kapitel_1_seite2_I1.jpg">'


def test_build_flashcards_deck_writes_preview_only_when_requested(tmp_path):
    cards = [{"front": "F1", "back": "B1"}, {"front": "F2", "back": "B2"}]
    out_path = tmp_path / "karteikarten.apkg"

    ka.build_flashcards_deck(cards, [], out_path, "Testdeck")
    assert not out_path.with_suffix(".preview.html").exists()

    preview_path = tmp_path / "karteikarten.preview.html"
    ka.build_flashcards_deck(cards, [], out_path, "Testdeck", preview_path=preview_path)
    assert preview_path.exists()
    assert "F1" in preview_path.read_text(encoding="utf-8")
