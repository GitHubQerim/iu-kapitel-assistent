#!/usr/bin/env python3
"""Erzeugt Zusammenfassungen oder Anki-Karteikarten aus Kapitel-PDFs per Copy&Paste in ein KI-Chat-Tool deiner Wahl (ChatGPT, Claude, Gemini, ...)."""
import argparse
import html
import json
import re
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

import markdown as markdown_lib
from pypdf import PdfReader

def build_summary_prompt(content: str, captions: list) -> str:
    intro = (
        "Du hilfst einem Studenten, nach einer Lernpause schnell wieder in ein Kapitel eines "
        "Studienskripts hineinzufinden.\n\n"
        "Fasse den folgenden Kapiteltext als prägnante Wiedereinstiegs-Zusammenfassung zusammen: "
        "die Kernbegriffe, die wichtigsten Zusammenhänge und was man sich für eine Prüfung merken sollte."
    )
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


def collect_all_captions(all_image_pages):
    captions = []
    for _, image_pages in all_image_pages:
        for _, _, page_captions in image_pages:
            captions.extend(c for c in page_captions if c)
    return captions


ABB_NUM_RE = re.compile(r"(?:Abbildung|Figure)\s+(\d+)")


def caption_key(text):
    if not text:
        return None
    match = ABB_NUM_RE.search(text)
    return match.group(1) if match else text.strip()


def attach_images_to_cards(cards, saved_images):
    """Hängt Bilder an die passende KI-generierte Karte an (Matching über die Abbildungsnummer).

    Gibt die Bilder zurück, die keiner Karte zugeordnet werden konnten (z. B. weil die KI
    keine Frage dazu erstellt hat, oder weil sich für das Bild gar keine Bildunterschrift
    zuordnen ließ) sowie die Pfade der bereits eingebetteten Bilder.
    """
    by_key = {}
    unkeyed = []
    for entry in saved_images:
        _, _, _, caption = entry
        key = caption_key(caption)
        if key is not None:
            by_key.setdefault(key, []).append(entry)
        else:
            unkeyed.append(entry)

    embedded_paths = []
    for card in cards:
        cap = card.get("image_caption")
        if not cap:
            continue
        matches = by_key.get(caption_key(cap))
        if matches:
            _, _, img_path, _ = matches.pop(0)
            card["back"] = f'{card["back"]}<br><img src="{img_path.name}">'
            embedded_paths.append(img_path)

    leftover = [entry for entries in by_key.values() for entry in entries] + unkeyed
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


IMAGE_MARKER_RE = re.compile(r"^\[\[ABBILDUNG:\s*(.+?)\]\]\s*$", re.MULTILINE)


def place_images_inline(md_text: str, saved_images, out_dir: Path):
    """Ersetzt [[ABBILDUNG: ...]]-Marker der KI durch das passende Bild an genau dieser Stelle.

    Matching läuft wie bei den Karteikarten über caption_key() (Abbildungsnummer), damit kleine
    Abweichungen im von der KI zurückgegebenen Bildunterschriften-Text nicht zum Scheitern führen.
    Bilder, die die KI nicht referenziert hat, werden als 'übrig' zurückgegeben statt verworfen.
    Das gilt auch für Bilder, denen sich gar keine Bildunterschrift zuordnen ließ.
    """
    by_key = {}
    unkeyed = []
    for entry in saved_images:
        _, _, _, caption = entry
        key = caption_key(caption)
        if key is not None:
            by_key.setdefault(key, []).append(entry)
        else:
            unkeyed.append(entry)

    def repl(m):
        matches = by_key.get(caption_key(m.group(1)))
        if not matches:
            return ""
        pdf_path, page_num, img_path, caption = matches.pop(0)
        rel = img_path.relative_to(out_dir)
        label = caption or f"{pdf_path.stem} Seite {page_num}"
        return f"![{label}]({rel})"

    placed_md = IMAGE_MARKER_RE.sub(repl, md_text)
    leftover = [entry for entries in by_key.values() for entry in entries] + unkeyed
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
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=Archivo:wght@400;500;600&family=Archivo+Black&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root{ --shell-bg:#E8EAEE; --shell-ink:#23262B; --shell-mut:#7A7F87; }
  *{margin:0;padding:0;box-sizing:border-box}
  body{ background:var(--shell-bg); font-family:'Inter',system-ui,sans-serif; color:var(--shell-ink); -webkit-font-smoothing:antialiased; }

  .shell-head{ max-width:900px;margin:0 auto;padding:36px 24px 4px;display:flex;justify-content:space-between;align-items:flex-start;gap:16px; }
  .shell-head h1{ font-family:'Space Grotesk',sans-serif;font-size:20px;font-weight:600;letter-spacing:-0.01em; }
  .shell-head p{ color:var(--shell-mut);font-size:13px;margin-top:5px; }
  .bar{ max-width:900px;margin:20px auto 0;padding:0 24px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap; }
  .tabs{ display:flex;gap:8px;flex-wrap:wrap; }
  .tab{ border:1px solid #C9CCD3;background:#F4F5F7;color:var(--shell-ink); padding:8px 16px;border-radius:999px;font-size:13.5px;font-weight:500; cursor:pointer;font-family:inherit;transition:all .15s ease; }
  .tab:hover{ background:#fff }
  .tab:focus-visible{ outline:2px solid #345995;outline-offset:2px }
  .tab[aria-selected="true"]{ background:#23262B;color:#fff;border-color:#23262B }
  .print-btn{ border:1px solid #C9CCD3;background:#fff;color:var(--shell-ink);padding:8px 16px;border-radius:999px;font-size:13.5px;font-weight:500;cursor:pointer;font-family:inherit; }
  .print-btn:hover{ border-color:#23262B }

  .stage{ max-width:900px;margin:20px auto 70px;padding:0 24px }
  .variant{ display:none }
  .variant.active{ display:block;animation:fadein .2s ease }
  @keyframes fadein{ from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:none} }

  .paper{ background:#fff;border-radius:6px; box-shadow:0 1px 2px rgba(20,22,26,.08),0 12px 32px rgba(20,22,26,.10); overflow:hidden; }

  .doc figure{ margin:26px 0;text-align:center }
  .doc img{ max-width:100%;max-height:440px;height:auto;width:auto;object-fit:contain;border-radius:8px;display:inline-block }
  .doc figcaption{ margin-top:8px;font-size:11.5px;color:var(--shell-mut);font-style:italic }

  /* Simpel */
  .v1 .paper{ padding:64px 24px }
  .v1 .doc{ max-width:620px;margin:0 auto;font-family:'IBM Plex Sans',sans-serif;color:#1B1E23 }
  .v1 .meta{ font-family:'IBM Plex Mono',monospace;font-size:12px;color:#6B7280; display:flex;gap:18px;flex-wrap:wrap;margin-bottom:26px; }
  .v1 .doc h1{ font-size:29px;font-weight:600;letter-spacing:-0.015em;line-height:1.2;margin-bottom:26px }
  .v1 .doc h2{ font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.09em;color:#345995;margin:36px 0 12px }
  .v1 .doc p{ font-size:15px;line-height:1.7;color:#2A2E34;margin-bottom:14px }
  .v1 .doc ul,.v1 .doc ol{ margin:0 0 14px;padding-left:0;list-style:none }
  .v1 .doc li{ font-size:15px;line-height:1.7;color:#2A2E34;padding-left:20px;position:relative;margin-bottom:8px }
  .v1 .doc ul li::before{ content:"—";position:absolute;left:0;color:#9AA0A8 }
  .v1 .doc ol{ counter-reset:v1step }
  .v1 .doc ol li{ counter-increment:v1step }
  .v1 .doc ol li::before{ content:counter(v1step)".";color:#345995;font-weight:600 }
  .v1 .doc strong{ font-weight:600;color:#1B1E23 }
  .v1 .doc code{ font-family:'IBM Plex Mono',monospace;font-size:13px;background:#F1F3F6;padding:2px 6px;border-radius:4px }
  .v1 .doc img{ box-shadow:0 1px 3px rgba(20,22,26,.14) }
  .v1 .doc footer{ margin-top:48px;padding-top:16px;border-top:1px solid #E5E7EB; font-family:'IBM Plex Mono',monospace;font-size:11px;color:#9AA0A8; }

  /* Medium */
  .v2 .paper{ background:#FBFBF9;padding:0 }
  .v2 .layout{ display:grid;grid-template-columns:1fr 220px;min-height:400px }
  .v2 .main{ padding:52px 48px;font-family:'Inter',sans-serif;color:#20242A }
  .v2 .rail{ background:#F1F1EC;border-left:1px solid #E2E2DB;padding:52px 26px;font-family:'Inter',sans-serif }
  .v2 .doc h1{ font-family:'Space Grotesk',sans-serif;font-size:28px;font-weight:700;letter-spacing:-0.02em;line-height:1.18;margin-bottom:18px }
  .v2 .doc h2{ font-family:'Space Grotesk',sans-serif;font-size:15.5px;font-weight:600;margin:32px 0 12px;display:flex;align-items:center;gap:10px }
  .v2 .doc h2::after{ content:"";flex:1;height:1px;background:#E4E4DD }
  .v2 .doc p{ font-size:14.5px;line-height:1.7;color:#33383F;margin-bottom:12px }
  .v2 .doc ul,.v2 .doc ol{ margin:0 0 12px;padding-left:0;list-style:none }
  .v2 .doc li{ font-size:14.5px;line-height:1.7;color:#33383F;padding-left:22px;position:relative;margin-bottom:7px }
  .v2 .doc ul li::before{ content:"";position:absolute;left:2px;top:8px;width:7px;height:7px;border-radius:2px;background:#0E7C66;opacity:.8 }
  .v2 .doc ol{ counter-reset:v2step }
  .v2 .doc ol li{ counter-increment:v2step }
  .v2 .doc ol li::before{ content:counter(v2step);position:absolute;left:0;top:1px;width:16px;height:16px;border-radius:50%;background:#0E7C66;color:#fff;font-size:10px;font-weight:600;display:flex;align-items:center;justify-content:center }
  .v2 .doc strong{ font-weight:600;color:#191D22 }
  .v2 .doc code{ font-family:'IBM Plex Mono',monospace;font-size:12.5px;background:#EDEDE6;padding:2px 6px;border-radius:4px }
  .v2 .doc img{ border:1px solid #E4E4DD }
  .v2 .rail h3{ font-family:'Space Grotesk',sans-serif;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:#8A8E85;margin-bottom:10px }
  .v2 .rail dl div{ margin-bottom:14px }
  .v2 .rail dt{ font-size:10.5px;color:#8A8E85 }
  .v2 .rail dd{ font-size:13px;font-weight:500;color:#2A2E34;margin-top:1px;font-family:'IBM Plex Mono',monospace;word-break:break-word }
  @media(max-width:720px){ .v2 .layout{grid-template-columns:1fr} .v2 .rail{border-left:none;border-top:1px solid #E2E2DB} .v2 .main{padding:36px 24px} }

  /* Fancy */
  .v3 .paper{ background:#F2F3EF;position:relative; background-image:radial-gradient(rgba(34,58,140,.05) 1px,transparent 1px);background-size:14px 14px; }
  .v3 .doc{ max-width:660px;margin:0 auto;padding:52px 40px 60px;font-family:'Archivo',sans-serif;color:#1E2128 }
  .v3 .topbar{ display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:30px; font-family:'Space Mono',monospace;font-size:11px;color:#223A8C; }
  .v3 .stamp{ border:2px solid #E8542F;color:#E8542F;padding:4px 11px;font-weight:700; letter-spacing:.08em;transform:rotate(3deg);font-size:10.5px;mix-blend-mode:multiply; }
  .v3 .doc h1{ font-family:'Archivo Black',sans-serif;font-size:clamp(28px,4.4vw,42px); line-height:1.05;letter-spacing:-0.015em;text-transform:uppercase;color:#223A8C;margin-bottom:26px; }
  .v3 .doc h2{ font-family:'Space Mono',monospace;font-size:12px;font-weight:700; text-transform:uppercase;letter-spacing:.14em;color:#E8542F;margin:30px 0 12px; }
  .v3 .doc p{ font-size:14.5px;line-height:1.68;color:#2B2F38;margin-bottom:12px }
  .v3 .doc ul,.v3 .doc ol{ margin:0 0 12px;padding-left:0;list-style:none }
  .v3 .doc li{ font-size:14px;line-height:1.68;color:#2B2F38;padding-left:24px;position:relative;margin-bottom:9px }
  .v3 .doc ul li::before{ content:"✕";position:absolute;left:0;top:0;color:#223A8C;font-size:11px;font-weight:700 }
  .v3 .doc ol{ counter-reset:v3step }
  .v3 .doc ol li{ counter-increment:v3step }
  .v3 .doc ol li::before{ content:counter(v3step);position:absolute;left:0;top:0;color:#E8542F;font-weight:700;font-family:'Space Mono',monospace }
  .v3 .doc strong{ font-weight:600;color:#223A8C }
  .v3 .doc code{ font-family:'Space Mono',monospace;font-size:12px;background:rgba(34,58,140,.09);padding:2px 6px }
  .v3 .doc img{ border:2px solid #223A8C }
  .v3 .doc figcaption{ font-family:'Space Mono',monospace;text-transform:uppercase;letter-spacing:.05em;font-size:10px }
  .v3 .doc footer{ margin-top:40px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px; font-family:'Space Mono',monospace;font-size:10px;color:#223A8C; border-top:2px solid #223A8C;padding-top:12px;text-transform:uppercase;letter-spacing:.06em; }
  @media(max-width:720px){ .v3 .doc{padding:36px 22px} }

  @media print{
    body{ background:#fff }
    .shell-head,.bar{ display:none }
    .stage{ margin:0;padding:0;max-width:none }
    .paper{ box-shadow:none;border-radius:0 }
    .variant{ display:none }
    .variant.active{ display:block }
  }
  @media (prefers-reduced-motion: reduce){ .variant.active{ animation:none } }
</style>
</head>
<body>

<header class="shell-head">
  <div>
    <h1>@@TITLE@@</h1>
    <p>Wiedereinstiegs-Zusammenfassung · Kapitel-Assistent</p>
  </div>
</header>

<div class="bar">
  <div class="tabs" role="tablist" aria-label="Design-Varianten">
    <button class="tab" role="tab" aria-selected="true" data-target="var-1">Simpel</button>
    <button class="tab" role="tab" aria-selected="false" data-target="var-2">Medium</button>
    <button class="tab" role="tab" aria-selected="false" data-target="var-3">Fancy</button>
  </div>
  <button class="print-btn" id="print-btn">Drucken</button>
</div>

<main class="stage">

<section class="variant v1 active" id="var-1" role="tabpanel">
  <div class="paper">
    <article class="doc">
      <div class="meta"><span>Quelle: @@SOURCE@@</span><span>Erstellt: @@GENERATED@@</span></div>
@@CONTENT@@
      <footer>generiert von Kapitel-Assistent</footer>
    </article>
  </div>
</section>

<section class="variant v2" id="var-2" role="tabpanel" hidden>
  <div class="paper">
    <div class="layout">
      <article class="main doc">
@@CONTENT@@
      </article>
      <aside class="rail">
        <h3>Meta</h3>
        <dl>
          <div><dt>Quelle</dt><dd>@@SOURCE@@</dd></div>
          <div><dt>Erstellt</dt><dd>@@GENERATED@@</dd></div>
        </dl>
      </aside>
    </div>
  </div>
</section>

<section class="variant v3" id="var-3" role="tabpanel" hidden>
  <div class="paper">
    <article class="doc">
      <div class="topbar">
        <div>QUELLE: @@SOURCE@@<br>ERSTELLT: @@GENERATED@@</div>
        <div class="stamp">AUTO-GENERIERT</div>
      </div>
@@CONTENT@@
      <footer><span>Kapitel-Assistent</span><span>@@SOURCE@@</span></footer>
    </article>
  </div>
</section>

</main>

<script>
  const tabs = document.querySelectorAll('.tab');
  const panels = document.querySelectorAll('.variant');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.setAttribute('aria-selected', 'false'));
      tab.setAttribute('aria-selected', 'true');
      panels.forEach(p => {
        const active = p.id === tab.dataset.target;
        p.classList.toggle('active', active);
        p.hidden = !active;
      });
    });
  });
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


def render_summary_html(md_text: str, source_names: list) -> str:
    """Rendert eine Zusammenfassung als eigenständige HTML-Datei mit drei Design-Varianten.

    Rein lokal (kein KI-Aufruf): der Inhalt kommt unverändert aus dem bereits
    gespeicherten Markdown, nur die Optik ändert sich zwischen den Tabs.
    """
    fallback_title = prettify_stem(Path(source_names[0]).stem) if source_names else "Zusammenfassung"
    title, body_md = split_title(md_text, fallback_title)
    content_html = markdown_lib.markdown(body_md, extensions=["extra", "sane_lists"])
    content_html = wrap_images_as_figures(content_html)
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


def record_summary(md_path: Path, html_path: Path, pdf_paths):
    label = prettify_stem(pdf_paths[0].stem) if pdf_paths else md_path.stem
    add_library_entry({
        "type": "summary",
        "label": label,
        "md_path": str(md_path),
        "html_path": str(html_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
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
    content, image_pages = build_content(pdf_paths)
    captions = collect_all_captions(image_pages)
    response = prompt_and_wait(build_summary_prompt(content, captions), "Zusammenfassung")

    out_path = Path(args.out)
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
    record_summary(out_path, html_path, pdf_paths)

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

    out_path = Path(args.out)
    deck_name = args.deck or pdf_paths[0].parent.name or pdf_paths[0].stem
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
