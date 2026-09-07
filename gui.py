#!/usr/bin/env python3
"""Desktop-Oberfläche für kapitel_assistent.py (pywebview + HTML/CSS in ui.html)."""
import subprocess
from pathlib import Path

import webview

from kapitel_assistent import (
    any_images_found,
    build_content,
    build_flashcards_deck,
    build_flashcards_prompt,
    build_sketch_prompt,
    build_summary_prompt,
    collect_all_captions,
    copy_to_clipboard,
    import_existing,
    is_unchanged_prompt,
    load_library,
    make_sketch_image_resolver,
    open_in_browser,
    organize_chapter_output,
    parse_flashcards,
    parse_sketch_response,
    place_images_inline,
    read_clipboard,
    record_flashcards,
    record_sketch,
    record_summary,
    render_summary_html,
    save_chapter_images,
)


def default_deck_name(first_pdf_path: Path) -> str:
    module_code = first_pdf_path.parent.name or "Kapitel-Assistent"
    label = first_pdf_path.stem.replace("_", " ")
    label = label[:1].upper() + label[1:] if label else label
    return f"{module_code}::{label}"


class Api:
    def __init__(self):
        self.window = None
        self.pdf_paths = []
        self.pending = None  # (pdf_paths, content, image_pages, options)
        self.last_prompt = None
        self.last_output_path = None

    def pick_files(self):
        paths = self.window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True, file_types=("PDF Dateien (*.pdf)",)
        )
        if not paths:
            return {"files": []}
        self.pdf_paths = list(paths)
        first = Path(self.pdf_paths[0])
        return {
            "files": [Path(p).name for p in self.pdf_paths],
            "default_output_base": first.stem,
            "default_output_dir": str(first.parent),
            "default_deck_name": default_deck_name(first),
        }

    def pick_output(self, ext):
        path = self.window.create_file_dialog(
            webview.SAVE_DIALOG, save_filename=f"ausgabe.{ext}"
        )
        return path or ""

    def copy_prompt(self, mode, options=None):
        if not self.pdf_paths:
            return {"ok": False, "error": "Bitte zuerst ein oder mehrere Kapitel-PDFs wählen."}

        options = options or {}
        pdf_paths = [Path(p) for p in self.pdf_paths]
        if mode == "sketch" and len(pdf_paths) != 1:
            return {
                "ok": False,
                "error": "Zusammenfassung 2.0 unterstützt nur genau ein PDF pro Kapitel "
                         "(echte Skript-Seitenzahlen sind PDF-lokal).",
            }
        include_images = options.get("include_images", True)
        # Im Sketch-Modus bedeutet "include_images" nur noch "KI darf Skizzen zeichnen"
        # (siehe build_sketch_prompt/allow_sketches) -- Bilder werden trotzdem IMMER
        # extrahiert, weil auch der "image"-Fallback pro Abbildung das echte Bild braucht.
        content, image_pages = build_content(
            pdf_paths, extract_images=True if mode == "sketch" else include_images,
            include_page_markers=(mode == "sketch"),
        )
        self.pending = (pdf_paths, content, image_pages, options)
        captions = collect_all_captions(image_pages)

        if mode == "flashcards":
            prompt = build_flashcards_prompt(content, captions)
        elif mode == "sketch":
            prompt = build_sketch_prompt(
                content, captions,
                detail_level=options.get("detail_level", "ausfuehrlich"),
                allow_sketches=include_images,
            )
        else:
            prompt = build_summary_prompt(
                content, captions,
                detail_level=options.get("detail_level", "ausfuehrlich"),
                include_glossary=options.get("include_glossary", False),
            )
        self.last_prompt = prompt
        copy_to_clipboard(prompt)
        return {"ok": True}

    def read_response(self, mode, out_path_str, deck_name=None):
        if not self.pending:
            return {"ok": False, "error": "Bitte zuerst auf 'Prompt kopieren' klicken."}
        if not out_path_str:
            return {"ok": False, "error": "Bitte eine Ausgabedatei wählen."}

        pdf_paths, content, image_pages, options = self.pending
        response = read_clipboard().strip()
        if not response:
            return {"ok": False, "error": "Zwischenablage ist leer. Antwort im Chat-Tool kopieren und erneut klicken."}
        if is_unchanged_prompt(response, self.last_prompt):
            return {
                "ok": False,
                "error": (
                    "In der Zwischenablage steht noch der Prompt selbst, nicht die Antwort des Chat-Tools. "
                    "Erst dort einfügen & abschicken, die Antwort abwarten, DIE ANTWORT kopieren – dann erneut klicken."
                ),
            }

        out_path = Path(out_path_str)
        expected_ext = ".apkg" if mode == "flashcards" else ".html" if mode == "sketch" else ".md"
        if out_path.suffix.lower() != expected_ext:
            out_path = out_path.with_suffix(expected_ext)

        try:
            if mode == "flashcards":
                name = deck_name or default_deck_name(pdf_paths[0])
                message, label = self._build_flashcards(response, image_pages, out_path, name, pdf_paths)
            elif mode == "sketch":
                message, label = self._build_sketch(response, image_pages, out_path, pdf_paths)
            else:
                message, label = self._build_summary(response, image_pages, out_path, pdf_paths, options)
        except ValueError as exc:
            return {
                "ok": False,
                "error": f"Antwort konnte nicht verarbeitet werden: {exc} "
                         "Korrigiere sie im Chat-Tool, kopiere sie neu und klicke wieder auf 'Antwort einlesen'.",
            }

        self.pending = None
        self.last_output_path = str(out_path)
        return {"ok": True, "message": message, "out_path": str(out_path), "label": label}

    def reveal_output(self):
        if self.last_output_path and Path(self.last_output_path).exists():
            subprocess.run(["open", "-R", self.last_output_path], check=False)
        return {"ok": True}

    def get_library(self):
        return {"entries": load_library()}

    def import_files(self):
        paths = self.window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True,
            file_types=("Zusammenfassungen & Decks (*.md;*.apkg)",),
        )
        if not paths:
            return {"ok": True, "count": 0}
        imported = import_existing(paths)
        return {"ok": True, "count": len(imported)}

    def open_library_item(self, index):
        entries = load_library()
        if not (0 <= index < len(entries)):
            return {"ok": False, "error": "Eintrag nicht gefunden."}
        entry = entries[index]
        if entry.get("type") in ("summary", "sketch") and entry.get("html_path") and Path(entry["html_path"]).exists():
            open_in_browser(Path(entry["html_path"]))
            return {"ok": True}
        if entry.get("apkg_path") and Path(entry["apkg_path"]).exists():
            subprocess.run(["open", "-R", entry["apkg_path"]], check=False)
            return {"ok": True}
        return {"ok": False, "error": "Datei nicht gefunden (evtl. verschoben oder gelöscht)."}

    def _build_summary(self, response, image_pages, out_path: Path, pdf_paths, options=None):
        options = options or {}
        out_path = organize_chapter_output(out_path, pdf_paths)
        saved_images = save_chapter_images(image_pages, out_path.parent / f"{out_path.stem}_bilder")
        full_md, leftover_images = place_images_inline(response, saved_images, out_path.parent)

        if leftover_images:
            images_section = "\n\n## Weitere Bilder aus diesem Kapitel\n\n"
            for pdf_path, page_num, img_path, caption in leftover_images:
                rel = img_path.relative_to(out_path.parent)
                label = caption or f"{pdf_path.stem} Seite {page_num}"
                images_section += f"![{label}]({rel})\n\n"
            full_md += images_section

        out_path.write_text(full_md, encoding="utf-8")

        html_path = out_path.with_suffix(".html")
        html_path.write_text(render_summary_html(full_md, [p.name for p in pdf_paths]), encoding="utf-8")
        open_in_browser(html_path)
        label = record_summary(
            out_path, html_path, pdf_paths,
            detail_level=options.get("detail_level"),
            has_images=any_images_found(image_pages),
            has_glossary=options.get("include_glossary"),
        )

        if saved_images:
            placed = len(saved_images) - len(leftover_images)
            extra = f", {len(leftover_images)} zusätzlich angehängt" if leftover_images else ""
            message = f"Zusammenfassung gespeichert. {placed} Bild(er) im Text platziert{extra}. HTML-Ansicht geöffnet."
        else:
            message = "Zusammenfassung gespeichert. HTML-Ansicht geöffnet."
        return message, label

    def _build_flashcards(self, response, image_pages, out_path: Path, deck_name: str, pdf_paths):
        cards = parse_flashcards(response)
        out_path = organize_chapter_output(out_path, pdf_paths)
        total, with_image, extra_image_cards = build_flashcards_deck(cards, image_pages, out_path, deck_name)
        record_flashcards(out_path, deck_name)
        message = f"{total} Karteikarte(n) ({with_image} mit Bild) + {extra_image_cards} zusätzliche Bild-Karte(n)."
        return message, deck_name

    def _build_sketch(self, response, image_pages, out_path: Path, pdf_paths):
        from render.sketch import render_sketch, render_sketch_pdf

        data = parse_sketch_response(response)
        out_path = organize_chapter_output(out_path, pdf_paths)
        saved_images = save_chapter_images(image_pages, out_path.parent / f"{out_path.stem}_bilder")
        resolver = make_sketch_image_resolver(saved_images, out_path.parent)
        render_sketch(data, out_path, image_resolver=resolver)
        pdf_path, pdf_hint = render_sketch_pdf(out_path)
        open_in_browser(out_path)
        label = record_sketch(out_path, pdf_paths)
        message = "Sketch-Lernblatt gespeichert. HTML-Ansicht geöffnet."
        message += f" PDF-Export: {pdf_path.name}." if pdf_path else f" {pdf_hint}"
        return message, label


if __name__ == "__main__":
    api = Api()
    html_path = Path(__file__).parent / "ui.html"
    window = webview.create_window(
        "Kapitel-Assistent", url=str(html_path), js_api=api, width=760, height=640, min_size=(620, 520)
    )
    api.window = window
    webview.start()
