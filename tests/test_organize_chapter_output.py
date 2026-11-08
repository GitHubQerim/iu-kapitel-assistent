import kapitel_assistent as ka


def test_summary_and_flashcards_land_in_the_same_chapter_folder(tmp_path):
    """Regression guard: the chapter folder used to be named after out_path.stem, so
    summary (default --out zusammenfassung.md) and flashcards (default --out
    karteikarten.apkg) for the SAME chapter PDF ended up in two different sibling
    folders ("Zusammenfassung" / "Karteikarten") instead of together."""
    pdf_path = tmp_path / "kapitel_1_einfuehrung.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    summary_out = ka.organize_chapter_output(tmp_path / "zusammenfassung.md", [pdf_path])
    flashcards_out = ka.organize_chapter_output(tmp_path / "karteikarten.apkg", [pdf_path])

    assert summary_out.parent == flashcards_out.parent
    assert summary_out.parent.name == "Kapitel 1 einfuehrung"
    assert (summary_out.parent / "kapitel_1_einfuehrung.pdf").exists()


def test_is_idempotent_when_called_again_for_an_already_moved_pdf(tmp_path):
    pdf_path = tmp_path / "kapitel_2.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    first = ka.organize_chapter_output(tmp_path / "zusammenfassung.md", [pdf_path])
    second = ka.organize_chapter_output(tmp_path / "zusammenfassung.md", [pdf_path])

    assert first == second
    assert (first.parent / "kapitel_2.pdf").exists()
