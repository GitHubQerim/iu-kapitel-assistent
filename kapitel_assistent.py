#!/usr/bin/env python3
"""Erzeugt Zusammenfassungen oder Anki-Karteikarten aus Kapitel-PDFs per Copy&Paste in ein KI-Chat-Tool deiner Wahl (ChatGPT, Claude, Gemini, ...)."""
import argparse
import html
import json
import re
import shutil
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

import markdown as markdown_lib
from pypdf import PdfReader

DETAIL_INSTRUCTIONS = {
    "kurz": (
        "Fasse dich dabei bewusst kurz und knapp: nur die wichtigsten Kernbegriffe und "
        "Kernaussagen in Stichpunkten, ohne ausführliche Erklärungen, Beispiele oder Herleitungen."
    ),
    "ausfuehrlich": (
        "Gehe dabei ausführlich genug ins Detail, dass die Zusammenfassung auch ohne erneutes "
        "Lesen des Originaltexts zum inhaltlichen Verständnis ausreicht."
    ),
}


def build_summary_prompt(content: str, captions: list, detail_level: str = "ausfuehrlich",
                          include_glossary: bool = False) -> str:
    intro = (
        "Du hilfst einem Studenten, nach einer Lernpause schnell wieder in ein Kapitel eines "
        "Studienskripts hineinzufinden.\n\n"
        "Fasse den folgenden Kapiteltext als prägnante Wiedereinstiegs-Zusammenfassung zusammen: "
        "die Kernbegriffe, die wichtigsten Zusammenhänge und was man sich für eine Prüfung merken sollte."
    )
    intro += "\n\n" + DETAIL_INSTRUCTIONS.get(detail_level, DETAIL_INSTRUCTIONS["ausfuehrlich"])
    if captions:
        caption_block = "\n".join(f"- {c}" for c in captions)
        intro += (
            "\n\nIm Kapitel gibt es außerdem folgende Abbildungen:\n"
            f"{caption_block}\n\n"
            "Wenn eine Abbildung inhaltlich zu einem Abschnitt deiner Zusammenfassung passt, "
            "verweise an genau der passenden Stelle im Fließtext in einer EIGENEN Zeile darauf, "
            "im exakten Format [[ABBILDUNG: <Bildunterschriften-Text von oben, exakt kopiert>]]. "
            "Nicht jede Abbildung muss referenziert werden — nur die, die wirklich zum jeweiligen "
            "Abschnitt passt."
        )
    if include_glossary:
        intro += (
            '\n\nErgänze vor dem Abschluss einen eigenen Abschnitt mit der exakten Überschrift '
            '"## Glossar", der die wichtigsten Fachbegriffe aus dem Kapitel kurz und verständlich erklärt.'
        )
    intro += (
        "\n\nBeende deine Zusammenfassung IMMER mit einem eigenen Abschnitt mit der exakten "
        'Überschrift "## Prüfungs-Merkliste in Kürze", der die wichtigsten Begriffe, Formeln und '
        "Fakten aus dem Kapitel noch einmal knapp in Stichpunkten auflistet."
    )
    intro += (
        '\n\nAntworte NUR mit der Zusammenfassung selbst (Markdown), ohne einleitende Sätze wie '
        '"Hier ist...".'
    )
    return f"{intro}\n\n---\n{content}\n"


def build_flashcards_prompt(content: str, captions: list) -> str:
    intro = (
        "Erstelle aus dem folgenden Kapiteltext eines Studienskripts Karteikarten "
        "(Frage/Antwort) zum Lernen mit Spaced Repetition.\n"
    )
    image_field_hint = ""
    if captions:
        caption_block = "\n".join(f"- {c}" for c in captions)
        intro += (
            "\nIm Kapitel gibt es außerdem folgende Abbildungen. Erstelle zu JEDER davon "
            "ebenfalls eine Karteikarte mit einer echten Verständnisfrage (nicht nur die "
            "Bildunterschrift als Frage), die durch die Abbildung beantwortet bzw. erklärt "
            'wird. Setze bei diesen Karten zusätzlich ein Feld "image_caption" auf EXAKT '
            f"den folgenden Text:\n{caption_block}\n"
        )
        image_field_hint = (
            '\nKarten zu einer Abbildung bekommen zusätzlich das Feld "image_caption" mit '
            "dem exakten Bildunterschriften-Text von oben, andere Karten lassen dieses Feld weg."
        )

    return (
        f"{intro}\n"
        "Antworte AUSSCHLIESSLICH mit einem JSON-Array, nichts davor und nichts danach "
        "(keine Erklärung, kein Markdown-Codeblock, keine Rückfrage). Format exakt:\n"
        '[{"front": "Frage", "back": "Antwort"}, ...]'
        f"{image_field_hint}\n"
        "\n---\n"
        f"{content}\n"
    )


CAPTION_START_RE = re.compile(r"^(?:Abbildung|Figure)\s+\d+[:.]")
SOURCE_LINE_RE = re.compile(r"^(?:Quelle|Source):")


def extract_captions(page_text: str):
    """Findet 'Abbildung N: ...'- bzw. 'Figure N: ...'-Bildunterschriften im extrahierten Seitentext.

    IU-Skripte platzieren diese direkt bei der Abbildung, gefolgt von einer
    'Quelle:'/'Source:'-Zeile. Manche Skripte (auch deutschsprachige) beschriften Abbildungen
    auf Englisch ("Figure N: ..." / "Source: ..."). Eine Unterschrift kann über mehrere Zeilen
    umbrechen.
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


def resolve_pdf_path(path: Path) -> Path:
    """Findet eine PDF auch dann, wenn organize_chapter_output() sie inzwischen in einen
    Kapitel-Unterordner verschoben hat (z. B. weil zuerst die Zusammenfassung und danach die
    Karteikarten für dieselbe PDF-Auswahl erzeugt werden, siehe dort)."""
    if path.exists():
        return path
    matches = sorted(path.parent.glob(f"*/{path.name}")) if path.parent.exists() else []
    if len(matches) == 1:
        return matches[0]
    hint = f" (mehrere Treffer: {[str(m) for m in matches]})" if len(matches) > 1 else ""
    raise FileNotFoundError(f"PDF nicht gefunden: {path}{hint}")


def extract_chapter(pdf_path: Path, extract_images: bool = True):
    reader = PdfReader(resolve_pdf_path(pdf_path))
    text_parts = []
    image_pages = []
    for i, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        text_parts.append(page_text)
        if extract_images and page.images:
            images = list(page.images)
            captions = extract_captions(page_text)
            if len(captions) != len(images):
                captions = [None] * len(images)
            image_pages.append((i, images, captions))
    return "\n".join(text_parts), image_pages


def build_content(pdf_paths, extract_images: bool = True):
    sections = []
    all_image_pages = []
    for pdf_path in pdf_paths:
        text, image_pages = extract_chapter(pdf_path, extract_images=extract_images)
        sections.append(f"## Quelle: {pdf_path.name}\n\n{text}")
        all_image_pages.append((pdf_path, image_pages))
    return "\n\n".join(sections), all_image_pages


def collect_all_captions(all_image_pages):
    captions = []
    for _, image_pages in all_image_pages:
        for _, _, page_captions in image_pages:
            captions.extend(c for c in page_captions if c)
    return captions


def any_images_found(all_image_pages):
    """True, wenn mindestens ein PDF tatsächlich Bilder enthielt (all_image_pages hat sonst
    unabhängig davon immer einen Eintrag pro PDF, auch wenn dessen Bildliste leer ist)."""
    return any(image_pages for _, image_pages in all_image_pages)


ABB_NUM_RE = re.compile(r"(?:Abbildung|Figure)\s+(\d+)")
CAPTION_PREFIX_RE = re.compile(r"^(?:Abbildung|Figure)\s+\d+[:.]\s*")


def caption_key(text):
    if not text:
        return None
    match = ABB_NUM_RE.search(text)
    return match.group(1) if match else text.strip()


def caption_text_key(text):
    """Normalisierter Beschreibungstext ohne 'Abbildung N:'-Präfix, als Fallback-Key.

    Manche KIs kopieren beim Referenzieren einer Abbildung nur die Beschreibung, nicht die
    vorangestellte Nummer ("Abbildung 1: "). Dann liefert caption_key() für das Original (Key
    "1") und den KI-Text (Key "Informationen, Daten und Signale") unterschiedliche Werte, das
    Matching schlägt fehl. Dieser Key vergleicht stattdessen die Beschreibung selbst.
    """
    if not text:
        return None
    stripped = CAPTION_PREFIX_RE.sub("", text).strip()
    normalized = re.sub(r"\s+", " ", stripped).lower()
    return normalized or None


def _build_image_pool(saved_images):
    return [{"entry": entry, "caption": entry[3], "used": False} for entry in saved_images]


def _pop_matching_image(pool, raw_caption):
    """Sucht im Bilder-Pool zuerst über die Abbildungsnummer, dann über den Beschreibungstext."""
    key = caption_key(raw_caption)
    if key is not None:
        for item in pool:
            if not item["used"] and caption_key(item["caption"]) == key:
                item["used"] = True
                return item["entry"]
    text_key = caption_text_key(raw_caption)
    if text_key is not None:
        for item in pool:
            if not item["used"] and caption_text_key(item["caption"]) == text_key:
                item["used"] = True
                return item["entry"]
    return None


def attach_images_to_cards(cards, saved_images):
    """Hängt Bilder an die passende KI-generierte Karte an (Matching über die Abbildungsnummer,
    mit Fallback auf den Beschreibungstext, siehe caption_text_key()).

    Gibt die Bilder zurück, die keiner Karte zugeordnet werden konnten (z. B. weil die KI
    keine Frage dazu erstellt hat, oder weil sich für das Bild gar keine Bildunterschrift
    zuordnen ließ) sowie die Pfade der bereits eingebetteten Bilder.
    """
    pool = _build_image_pool(saved_images)

    embedded_paths = []
    for card in cards:
        cap = card.get("image_caption")
        if not cap:
            continue
        match = _pop_matching_image(pool, cap)
        if match:
            _, _, img_path, _ = match
            card["back"] = f'{card["back"]}<br><img src="{img_path.name}">'
            embedded_paths.append(img_path)

    leftover = [item["entry"] for item in pool if not item["used"]]
    return leftover, embedded_paths


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


def organize_chapter_output(out_path: Path, pdf_paths) -> Path:
    """Legt einen Kapitel-Unterordner an (Name = prettify_stem(out_path.stem)) und verschiebt
    die Quell-PDFs hinein, damit PDF, Zusammenfassung/Karteikarten, Bilder und HTML-Ansicht
    eines Kapitels nicht mehr flach im Modulordner verstreut sind.

    Idempotent: eine PDF, die schon im Zielordner liegt, wird nicht erneut verschoben.
    """
    folder = out_path.parent / prettify_stem(out_path.stem)
    folder.mkdir(parents=True, exist_ok=True)
    for pdf_path in pdf_paths:
        resolved = resolve_pdf_path(pdf_path)
        if resolved.parent != folder:
            shutil.move(str(resolved), str(folder / resolved.name))
    return folder / out_path.name


IMAGE_MARKER_RE = re.compile(r"^\[\[ABBILDUNG:\s*(.+?)\]\]\s*$", re.MULTILINE)


def place_images_inline(md_text: str, saved_images, out_dir: Path):
    """Ersetzt [[ABBILDUNG: ...]]-Marker der KI durch das passende Bild an genau dieser Stelle.

    Matching läuft wie bei den Karteikarten über caption_key() (Abbildungsnummer) mit Fallback
    auf caption_text_key() (Beschreibungstext), damit sowohl kleine Abweichungen als auch ein
    von der KI weggelassenes "Abbildung N:"-Präfix nicht zum Scheitern führen.
    Bilder, die die KI nicht referenziert hat, werden als 'übrig' zurückgegeben statt verworfen.
    Das gilt auch für Bilder, denen sich gar keine Bildunterschrift zuordnen ließ.
    """
    pool = _build_image_pool(saved_images)

    def repl(m):
        match = _pop_matching_image(pool, m.group(1))
        if not match:
            return ""
        pdf_path, page_num, img_path, caption = match
        rel = img_path.relative_to(out_dir)
        label = caption or f"{pdf_path.stem} Seite {page_num}"
        # Leerzeilen erzwingen: die KI setzt den Marker zwar auf eine eigene Zeile,
        # aber ohne Leerzeile drumherum verschmilzt Markdown das Bild sonst mit dem
        # umgebenden Absatz (oder macht es bei einer folgenden "---"-Zeile zur
        # Setext-Überschrift) – dann bleibt es ein ungebremstes <img> ohne Breitenlimit.
        return f"\n\n![{label}]({rel})\n\n"

    placed_md = IMAGE_MARKER_RE.sub(repl, md_text)
    leftover = [item["entry"] for item in pool if not item["used"]]
    return placed_md, leftover


def prettify_stem(stem: str) -> str:
    label = stem.replace("_", " ").replace("-", " ").strip()
    return label[:1].upper() + label[1:] if label else label


def split_title(md_text: str, fallback: str):
    """Trennt eine führende '# Titel'-Zeile vom restlichen Markdown ab, falls vorhanden."""
    stripped = md_text.strip()
    lines = stripped.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:]).strip()
    return fallback, stripped


SUMMARY_HTML_TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Zusammenfassung · @@TITLE@@</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --ink:#2A2E34; --mut:#8A8579;
    --c0:#E8542F; /* Koralle */
    --c1:#0E7C66; /* Petrol */
    --c2:#345995; /* Indigo */
    --c3:#A83279; /* Beere */
  }
  *{margin:0;padding:0;box-sizing:border-box}
  img{ max-width:100% }
  body{
    background:#FAF3E7; color:var(--ink); font-family:'IBM Plex Sans',system-ui,sans-serif;
    -webkit-font-smoothing:antialiased;
    background-image:radial-gradient(rgba(42,46,52,.05) 1px,transparent 1px);
    background-size:16px 16px;
  }

  .page{ max-width:760px;margin:0 auto;padding:48px 24px 90px }

  .top{ display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:8px }
  .print-btn{ border:1.5px solid var(--ink);background:#fff;color:var(--ink);padding:7px 16px;border-radius:999px;font-size:13px;font-weight:500;cursor:pointer;font-family:'IBM Plex Sans',sans-serif;flex:none }
  .print-btn:hover{ background:var(--ink);color:#fff }

  h1{
    font-family:'Caveat',cursive;font-weight:700;font-size:clamp(38px,7vw,58px);
    line-height:1.1;color:var(--ink);
    text-decoration:underline wavy var(--c0);text-decoration-thickness:2.5px;text-underline-offset:8px;
    margin-bottom:30px;
  }

  .intro{ font-size:15.5px;line-height:1.75;color:var(--ink);margin-bottom:30px }

  .note{
    position:relative;background:#FFFDF8;border-radius:5px;
    box-shadow:0 1px 2px rgba(30,25,15,.06),0 10px 26px rgba(30,25,15,.09);
    padding:32px 30px 30px;margin:0 0 40px;
  }
  .note:nth-of-type(odd){ transform:rotate(-0.5deg) }
  .note:nth-of-type(even){ transform:rotate(0.45deg) }
  .note::before{
    content:"";position:absolute;top:-13px;left:36px;width:76px;height:22px;
    background:var(--tape,var(--c0));opacity:.5;transform:rotate(-3deg);
    box-shadow:0 1px 2px rgba(30,25,15,.15);
  }
  .note-0{ --tape:var(--c0) } .note-0 h2{ color:var(--c0);text-decoration-color:var(--c0) }
  .note-1{ --tape:var(--c1) } .note-1 h2{ color:var(--c1);text-decoration-color:var(--c1) }
  .note-2{ --tape:var(--c2) } .note-2 h2{ color:var(--c2);text-decoration-color:var(--c2) }
  .note-3{ --tape:var(--c3) } .note-3 h2{ color:var(--c3);text-decoration-color:var(--c3) }

  h2{
    font-family:'Caveat',cursive;font-weight:700;font-size:30px;line-height:1.15;
    text-decoration:underline wavy;text-decoration-thickness:2px;text-underline-offset:6px;
    margin-bottom:14px;
  }
  .note > h2:first-child{ margin-top:0 }
  p{ font-size:15.5px;line-height:1.75;color:var(--ink);margin-bottom:13px }
  ul,ol{ margin:0 0 13px;padding-left:0;list-style:none }
  li{ font-size:15.5px;line-height:1.75;color:var(--ink);padding-left:22px;position:relative;margin-bottom:8px }
  ul li::before{ content:"";position:absolute;left:2px;top:9px;width:7px;height:7px;border-radius:50%;background:var(--tape,var(--c0)) }
  ol{ counter-reset:step }
  ol li{ counter-increment:step }
  ol li::before{ content:counter(step)".";color:var(--tape,var(--c0));font-weight:600;font-family:'IBM Plex Mono',monospace;font-size:13px }
  strong{ font-weight:600;color:#1B1E23 }
  code{ font-family:'IBM Plex Mono',monospace;font-size:13px;background:#F1EDE2;padding:2px 6px;border-radius:4px }

  figure{ margin:26px auto;text-align:center;max-width:420px }
  figure:nth-of-type(odd){ transform:rotate(-1.1deg) }
  figure:nth-of-type(even){ transform:rotate(1.3deg) }
  figure img{
    max-width:100%;max-height:380px;height:auto;width:auto;object-fit:contain;display:block;
    background:#fff;border:1px solid #EAE3D2;padding:10px 10px 30px;
    box-shadow:0 2px 4px rgba(30,25,15,.10),0 10px 22px rgba(30,25,15,.14);
  }
  figcaption{ margin-top:-22px;font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:var(--mut);font-style:italic }

  footer{ text-align:center;font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--mut);margin-top:20px }

  @media print{
    body{ background:#fff;background-image:none }
    .print-btn{ display:none }
    .note{ box-shadow:none;transform:none }
    .note::before{ display:none }
    .note > h2:first-child{ break-after:avoid }
    .note-last{ break-before:page }
    figure{ transform:none;break-inside:avoid }
  }
</style>
</head>
<body>

<main class="page">
  <div class="top">
    <h1>@@TITLE@@</h1>
    <button class="print-btn" id="print-btn">Drucken</button>
  </div>

@@CONTENT@@

  <footer>Kapitel-Assistent · @@SOURCE@@ · @@GENERATED@@</footer>
</main>

<script>
  document.getElementById('print-btn').addEventListener('click', () => window.print());
</script>
</body>
</html>
"""


IMG_PARAGRAPH_RE = re.compile(r'<p><img alt="([^"]*)" src="([^"]*)"\s*/?>\s*</p>')


def wrap_images_as_figures(content_html: str) -> str:
    """Macht die Bildunterschrift (Markdown-Alt-Text) sichtbar und begrenzt versehentlich riesige Bilder."""
    def repl(m):
        alt, src = m.group(1), m.group(2)
        caption = f"<figcaption>{alt}</figcaption>" if alt else ""
        return f'<figure><img src="{src}" alt="{alt}" loading="lazy">{caption}</figure>'
    return IMG_PARAGRAPH_RE.sub(repl, content_html)


NOTE_COLOR_COUNT = 4
H2_SPLIT_RE = re.compile(r'(?=<h2\b)')
MERKLISTE_HEADING_RE = re.compile(r'<h2>(?:(?!</h2>).)*?pr[uü]fungs-?merkliste', re.IGNORECASE | re.DOTALL)


def wrap_sections_as_notes(content_html: str) -> str:
    """Gruppiert den Inhalt nach H2-Überschriften in Karten mit rotierenden Akzentfarben.

    Text vor der ersten H2 (falls vorhanden) bleibt ohne Karten-Wrapper. Enthält der Inhalt
    gar keine H2 (z. B. weil die einzige Überschrift als Seitentitel verwendet wurde), wird
    trotzdem alles als eine Karte dargestellt statt unformatiert zu bleiben.
    """
    parts = H2_SPLIT_RE.split(content_html)
    intro, sections = parts[0], parts[1:]
    if not sections:
        return f'<section class="note note-0">{intro}</section>' if intro.strip() else ""
    wrapped = [f'<div class="intro">{intro}</div>'] if intro.strip() else []
    break_index = next((i for i, s in enumerate(sections) if MERKLISTE_HEADING_RE.match(s)), None)
    if break_index is None and len(sections) > 1:
        break_index = len(sections) - 1
    for i, section in enumerate(sections):
        extra = " note-last" if i == break_index else ""
        wrapped.append(f'<section class="note note-{i % NOTE_COLOR_COUNT}{extra}">{section}</section>')
    return "".join(wrapped)


LEADING_H2_RE = re.compile(r'^<h2>(.*?)</h2>\s*')


def promote_leading_heading(content_html: str, title: str, fallback_title: str):
    """Vermeidet doppelte Titel: Fängt der Inhalt direkt mit einer H2 an (kein Fließtext davor),
    ist das die EINZIGE H2 im ganzen Inhalt und wurde der Seitentitel nur aus dem Dateinamen
    abgeleitet, wird die H2 stattdessen zum Seitentitel befördert – statt "Kapitel 1 ..." als
    Titel UND "Lektion 1 – ..." als erste Überschrift redundant untereinander zu zeigen.

    Auf mehrere H2 beschränkt sich das bewusst NICHT: dort ist die erste Überschrift meist ein
    eigenständiger erster Abschnitt (z. B. "Grundbegriffe der Statistik") und keine Wiederholung
    des Kapiteltitels – die würde sonst fälschlich aus dem Text entfernt.
    """
    if title != fallback_title:
        return title, content_html
    m = LEADING_H2_RE.match(content_html)
    if not m:
        return title, content_html
    if "<h2" in content_html[m.end():]:
        return title, content_html
    promoted = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    if not promoted:
        return title, content_html
    return promoted, content_html[m.end():]


def render_summary_html(md_text: str, source_names: list) -> str:
    """Rendert eine Zusammenfassung als eigenständige, handgemacht wirkende HTML-Datei.

    Rein lokal (kein KI-Aufruf): der Inhalt kommt unverändert aus dem bereits
    gespeicherten Markdown, nur die Optik wird ergänzt.
    """
    fallback_title = prettify_stem(Path(source_names[0]).stem) if source_names else "Zusammenfassung"
    title, body_md = split_title(md_text, fallback_title)
    content_html = markdown_lib.markdown(body_md, extensions=["extra", "sane_lists"])
    title, content_html = promote_leading_heading(content_html, title, fallback_title)
    content_html = wrap_images_as_figures(content_html)
    content_html = wrap_sections_as_notes(content_html)
    source_line = ", ".join(source_names) if source_names else "unbekannt"
    generated_at = datetime.now().strftime("%d.%m.%Y, %H:%M")

    out = SUMMARY_HTML_TEMPLATE
    out = out.replace("@@TITLE@@", html.escape(title))
    out = out.replace("@@SOURCE@@", html.escape(source_line))
    out = out.replace("@@GENERATED@@", html.escape(generated_at))
    out = out.replace("@@CONTENT@@", content_html)
    return out


def open_in_browser(path: Path):
    webbrowser.open(path.resolve().as_uri())


LIBRARY_PATH = Path.home() / ".kapitel-assistent" / "library.json"


def load_library():
    if not LIBRARY_PATH.exists():
        return []
    try:
        return json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def add_library_entry(entry: dict):
    entries = load_library()
    entries.append(entry)
    LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIBRARY_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def record_summary(md_path: Path, html_path: Path, pdf_paths, detail_level=None, has_images=None,
                    has_glossary=None):
    label = prettify_stem(pdf_paths[0].stem) if pdf_paths else md_path.stem
    entry = {
        "type": "summary",
        "label": label,
        "md_path": str(md_path),
        "html_path": str(html_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if detail_level is not None:
        entry["detail_level"] = detail_level
    if has_images is not None:
        entry["has_images"] = has_images
    if has_glossary is not None:
        entry["has_glossary"] = has_glossary
    add_library_entry(entry)
    return label


def record_flashcards(apkg_path: Path, deck_name: str):
    add_library_entry({
        "type": "flashcards",
        "label": deck_name,
        "apkg_path": str(apkg_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })


def import_existing(paths) -> list:
    """Nimmt bereits vorhandene .md-/.apkg-Dateien (aus der Zeit vor der Bibliothek) nachträglich auf.

    Bei .md-Dateien wird die HTML-Ansicht dabei (neu) gerendert, falls sie noch fehlt.
    """
    imported = []
    for raw in paths:
        p = Path(raw)
        if p.suffix.lower() == ".md":
            md_text = p.read_text(encoding="utf-8")
            html_path = p.with_suffix(".html")
            html_path.write_text(render_summary_html(md_text, [p.name]), encoding="utf-8")
            label = record_summary(p, html_path, [p])
            imported.append((p, label))
        elif p.suffix.lower() == ".apkg":
            deck_name = prettify_stem(p.stem)
            record_flashcards(p, deck_name)
            imported.append((p, deck_name))
    return imported


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
    content, image_pages = build_content(pdf_paths, extract_images=args.images)
    captions = collect_all_captions(image_pages)
    prompt = build_summary_prompt(content, captions, detail_level=args.detail,
                                   include_glossary=args.glossar)
    response = prompt_and_wait(prompt, "Zusammenfassung")

    out_path = organize_chapter_output(Path(args.out), pdf_paths)
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
    record_summary(out_path, html_path, pdf_paths, detail_level=args.detail,
                    has_images=any_images_found(image_pages), has_glossary=args.glossar)

    print(f"Zusammenfassung gespeichert: {out_path}")
    if saved_images:
        placed = len(saved_images) - len(leftover_images)
        print(f"{placed} Bild(er) im Text platziert, {len(leftover_images)} zusätzlich angehängt.")
    print(f"HTML-Ansicht geöffnet: {html_path}")


def build_flashcards_deck(cards, image_pages, out_path: Path, deck_name: str):
    import genanki

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

    saved_images = save_chapter_images(image_pages, out_path.parent / f"{out_path.stem}_bilder")
    leftover_images, embedded_paths = attach_images_to_cards(cards, saved_images)

    for card in cards:
        deck.add_note(genanki.Note(model=model, fields=[card["front"], card["back"]]))

    media_files = [str(p) for p in embedded_paths]
    for pdf_path, page_num, img_path, caption in leftover_images:
        front = caption or f"Bild – {pdf_path.stem}, Seite {page_num}"
        deck.add_note(genanki.Note(model=model, fields=[front, f'<img src="{img_path.name}">']))
        media_files.append(str(img_path))

    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(str(out_path))

    return len(cards), len(embedded_paths), len(leftover_images)


def cmd_flashcards(args):
    pdf_paths = [Path(p) for p in args.pdfs]
    content, image_pages = build_content(pdf_paths)
    captions = collect_all_captions(image_pages)
    cards = prompt_and_wait(build_flashcards_prompt(content, captions), "Karteikarten", parse_flashcards)

    deck_name = args.deck or pdf_paths[0].parent.name or pdf_paths[0].stem
    out_path = organize_chapter_output(Path(args.out), pdf_paths)
    total, with_image, extra_image_cards = build_flashcards_deck(cards, image_pages, out_path, deck_name)
    record_flashcards(out_path, deck_name)

    print(f"{total} Karteikarte(n) ({with_image} mit Bild) + {extra_image_cards} zusätzliche Bild-Karte(n) gespeichert: {out_path}")


def cmd_import(args):
    imported = import_existing(args.files)
    for path, label in imported:
        print(f"Importiert: {label} ({path})")
    print(f"{len(imported)} Datei(en) in die Bibliothek aufgenommen.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_summary = sub.add_parser("summary", help="Wiedereinstiegs-Zusammenfassung erzeugen")
    p_summary.add_argument("pdfs", nargs="+", help="Ein oder mehrere Kapitel-PDFs")
    p_summary.add_argument("--out", default="zusammenfassung.md", help="Ausgabedatei (Markdown)")
    p_summary.add_argument("--detail", choices=["kurz", "ausfuehrlich"], default="ausfuehrlich",
                            help="Detailgrad der Zusammenfassung")
    p_summary.add_argument("--images", dest="images", action="store_true", default=True,
                            help="Abbildungen aus dem PDF extrahieren und einbetten (Standard)")
    p_summary.add_argument("--no-images", dest="images", action="store_false",
                            help="Keine Abbildungen extrahieren/einbetten")
    p_summary.add_argument("--glossar", action="store_true", default=False,
                            help="Zusätzlichen Glossar-Abschnitt anfordern")
    p_summary.set_defaults(func=cmd_summary)

    p_cards = sub.add_parser("flashcards", help="Anki-Karteikarten erzeugen")
    p_cards.add_argument("pdfs", nargs="+", help="Ein oder mehrere Kapitel-PDFs")
    p_cards.add_argument("--out", default="karteikarten.apkg", help="Ausgabedatei (.apkg)")
    p_cards.add_argument("--deck", default=None, help="Anki-Deck-Name (z. B. 'DLBMIUID01-01::Kapitel 8'); Standard: Ordnername")
    p_cards.set_defaults(func=cmd_flashcards)

    p_import = sub.add_parser("import", help="Bereits vorhandene .md-/.apkg-Dateien in die Bibliothek aufnehmen")
    p_import.add_argument("files", nargs="+", help="Eine oder mehrere .md- oder .apkg-Dateien")
    p_import.set_defaults(func=cmd_import)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
