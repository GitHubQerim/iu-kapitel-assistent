#!/usr/bin/env python3
"""Erzeugt Zusammenfassungen oder Anki-Karteikarten aus Kapitel-PDFs per Copy&Paste in ein KI-Chat-Tool deiner Wahl (ChatGPT, Claude, Gemini, ...)."""
import argparse
import json
import re
import subprocess
from pathlib import Path

from pypdf import PdfReader

SUMMARY_PROMPT = """Du hilfst einem Studenten, nach einer Lernpause schnell wieder in ein Kapitel eines Studienskripts hineinzufinden.

Fasse den folgenden Kapiteltext als prägnante Wiedereinstiegs-Zusammenfassung zusammen: die Kernbegriffe, die wichtigsten Zusammenhänge und was man sich für eine Prüfung merken sollte. Antworte NUR mit der Zusammenfassung selbst (Markdown), ohne einleitende Sätze wie "Hier ist...".

---
{content}
"""

FLASHCARDS_PROMPT = """Erstelle aus dem folgenden Kapiteltext eines Studienskripts Karteikarten (Frage/Antwort) zum Lernen mit Spaced Repetition.

Antworte AUSSCHLIESSLICH mit einem JSON-Array, nichts davor und nichts danach (keine Erklärung, kein Markdown-Codeblock, keine Rückfrage). Format exakt:
[{{"front": "Frage", "back": "Antwort"}}, ...]

---
{content}
"""


CAPTION_START_RE = re.compile(r"^Abbildung\s+\d+[:.]")
SOURCE_LINE_RE = re.compile(r"^Quelle:")


def extract_captions(page_text: str):
    """Findet 'Abbildung N: ...'-Bildunterschriften im extrahierten Seitentext.

    IU-Skripte platzieren diese direkt bei der Abbildung, gefolgt von einer
    'Quelle: ...'-Zeile. Eine Unterschrift kann über mehrere Zeilen umbrechen.
    """
    captions = []
    lines = page_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if CAPTION_START_RE.match(line):
            parts = [line]
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if SOURCE_LINE_RE.match(nxt) or CAPTION_START_RE.match(nxt):
                    break
                if nxt:
                    parts.append(nxt)
                i += 1
            captions.append(" ".join(parts))
            continue
        i += 1
    return captions


def extract_chapter(pdf_path: Path):
    reader = PdfReader(pdf_path)
    text_parts = []
    image_pages = []
    for i, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        text_parts.append(page_text)
        if page.images:
            images = list(page.images)
            captions = extract_captions(page_text)
            if len(captions) != len(images):
                captions = [None] * len(images)
            image_pages.append((i, images, captions))
    return "\n".join(text_parts), image_pages


def build_content(pdf_paths):
    sections = []
    all_image_pages = []
    for pdf_path in pdf_paths:
        text, image_pages = extract_chapter(pdf_path)
        sections.append(f"## Quelle: {pdf_path.name}\n\n{text}")
        all_image_pages.append((pdf_path, image_pages))
    return "\n\n".join(sections), all_image_pages


def copy_to_clipboard(text: str):
    subprocess.run(["pbcopy"], input=text, text=True, check=True)


def read_clipboard() -> str:
    return subprocess.run(["pbpaste"], capture_output=True, text=True, check=True).stdout


def save_chapter_images(all_image_pages, out_dir: Path):
    saved = []
    for pdf_path, pages in all_image_pages:
        for page_num, images, captions in pages:
            for img, caption in zip(images, captions):
                ext = Path(img.name).suffix or ".png"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"{pdf_path.stem}_seite{page_num}_{Path(img.name).stem}{ext}"
                out_path.write_bytes(img.data)
                saved.append((pdf_path, page_num, out_path, caption))
    return saved


def sanitize_json_candidate(text: str) -> str:
    replacements = {"“": '"', "”": '"', "‘": "'", "’": "'"}
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return re.sub(r",\s*([\]}])", r"\1", text)


def parse_flashcards(response: str):
    text = response.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)

    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("Kein JSON-Array in der Antwort gefunden.")

    candidate = match.group(0)
    for attempt in (candidate, sanitize_json_candidate(candidate)):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError as exc:
            last_error = exc

    from json_repair import repair_json

    try:
        repaired = json.loads(repair_json(candidate))
        if repaired:
            return repaired
    except (json.JSONDecodeError, ValueError):
        pass
    raise ValueError(f"JSON konnte nicht geparst werden ({last_error}).")


def is_unchanged_prompt(response: str, prompt: str) -> bool:
    return response.strip() == prompt.strip()


def prompt_and_wait(prompt: str, kind: str, parse_fn=lambda r: r):
    """Kopiert den Prompt in die Zwischenablage und wartet auf eine gültige Antwort.

    Bei einem Parse-Fehler wird NICHT abgebrochen: der Prompt bleibt in der
    Zwischenablage, man kann die Antwort im Chat-Tool korrigieren, neu kopieren
    und es erneut versuchen, ohne den ganzen Befehl neu starten zu müssen.
    """
    copy_to_clipboard(prompt)
    print(f"Prompt in die Zwischenablage kopiert ({kind}).")
    print("1) Füge ihn in ChatGPT/Claude/Gemini (o.ä.) ein  2) warte die Antwort ab  3) kopiere NUR die Antwort")
    while True:
        input("Drücke Enter, sobald die Antwort (nicht der Prompt!) in der Zwischenablage ist (Strg+C zum Abbrechen)...")
        response = read_clipboard().strip()
        if not response:
            print("Zwischenablage ist leer. Antwort kopieren und erneut Enter drücken.")
            continue
        if is_unchanged_prompt(response, prompt):
            print("In der Zwischenablage steht noch der Prompt selbst, nicht die Antwort des Chat-Tools.")
            print("Erst den Prompt einfügen und abschicken, die Antwort abwarten, DIE ANTWORT kopieren – dann erneut Enter.")
            continue
        try:
            return parse_fn(response)
        except ValueError as exc:
            print(f"Antwort konnte nicht verarbeitet werden: {exc}")
            print("Antwort im Chat-Tool korrigieren (oder neu anfragen), erneut kopieren und wieder Enter drücken.")


def cmd_summary(args):
    pdf_paths = [Path(p) for p in args.pdfs]
    content, image_pages = build_content(pdf_paths)
    response = prompt_and_wait(SUMMARY_PROMPT.format(content=content), "Zusammenfassung")

    out_path = Path(args.out)
    out_path.write_text(response, encoding="utf-8")

    saved_images = save_chapter_images(image_pages, out_path.parent / f"{out_path.stem}_bilder")
    if saved_images:
        with out_path.open("a", encoding="utf-8") as f:
            f.write("\n\n## Bilder aus diesem Kapitel\n\n")
            for pdf_path, page_num, img_path, caption in saved_images:
                rel = img_path.relative_to(out_path.parent)
                label = caption or f"{pdf_path.stem} Seite {page_num}"
                f.write(f"![{label}]({rel})\n\n")

    print(f"Zusammenfassung gespeichert: {out_path}")
    if saved_images:
        print(f"{len(saved_images)} Bild(er) aus dem Kapitel mit gespeichert.")


def cmd_flashcards(args):
    import genanki

    pdf_paths = [Path(p) for p in args.pdfs]
    content, image_pages = build_content(pdf_paths)
    cards = prompt_and_wait(FLASHCARDS_PROMPT.format(content=content), "Karteikarten", parse_flashcards)

    out_path = Path(args.out)
    deck_name = pdf_paths[0].parent.name or pdf_paths[0].stem
    deck_id = abs(hash(deck_name)) % (10**10)
    model_id = abs(hash(deck_name + "_model")) % (10**10)

    model = genanki.Model(
        model_id,
        "Kapitel-Assistent Basis",
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[
            {
                "name": "Karte",
                "qfmt": "{{Front}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
            }
        ],
    )
    deck = genanki.Deck(deck_id, deck_name)

    for card in cards:
        deck.add_note(genanki.Note(model=model, fields=[card["front"], card["back"]]))

    saved_images = save_chapter_images(image_pages, out_path.parent / f"{out_path.stem}_bilder")
    media_files = []
    for pdf_path, page_num, img_path, caption in saved_images:
        front = caption or f"Bild – {pdf_path.stem}, Seite {page_num}"
        deck.add_note(
            genanki.Note(
                model=model,
                fields=[front, f'<img src="{img_path.name}">'],
            )
        )
        media_files.append(str(img_path))

    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(str(out_path))

    print(f"{len(cards)} Karteikarte(n) + {len(saved_images)} Bild-Karte(n) gespeichert: {out_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_summary = sub.add_parser("summary", help="Wiedereinstiegs-Zusammenfassung erzeugen")
    p_summary.add_argument("pdfs", nargs="+", help="Ein oder mehrere Kapitel-PDFs")
    p_summary.add_argument("--out", default="zusammenfassung.md", help="Ausgabedatei (Markdown)")
    p_summary.set_defaults(func=cmd_summary)

    p_cards = sub.add_parser("flashcards", help="Anki-Karteikarten erzeugen")
    p_cards.add_argument("pdfs", nargs="+", help="Ein oder mehrere Kapitel-PDFs")
    p_cards.add_argument("--out", default="karteikarten.apkg", help="Ausgabedatei (.apkg)")
    p_cards.set_defaults(func=cmd_flashcards)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
