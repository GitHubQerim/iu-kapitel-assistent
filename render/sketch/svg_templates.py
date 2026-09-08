"""Parametrische SVG-Skizzen im Handschrift-Stil der Lernblatt-Referenz
(docs/reference/Lernblatt_Lektion1_Sketch.html).

Jede render_*-Funktion bekommt einen "sketch"-Block aus der KI-JSON-Antwort und gibt einen
fertigen <svg class="sk ...">-String zurueck. Strichstil (`.stroke` + `filter="url(#wob)"`)
und Text-Klassen (`.st`, `.cap`) sind aus der Referenz uebernommen; Positionen/Labels kommen
aus dem JSON, nicht hartkodiert.

Die Funktionen bilden den Look bewusst *parametrisch* nach, nicht Pixel-fuer-Pixel identisch
zur Referenz -- siehe Plan-Hinweis zur manuellen visuellen Abnahme.
"""
import html
import textwrap

FILL_CYCLE = ["fla", "fl", "fy", "fo", "fw"]

TEMPLATES = (
    "stack", "cycle", "layers", "rings", "triangle", "timeline", "flow", "image",
)

# Fuer render_cycle(): "sub"-Beschriftungen wurden bisher als EIN <text>-Element ohne
# Zeilenumbruch gerendert -- bei laengeren Saetzen (die die KI trotz kurzer Titel gern
# hinschreibt, z.B. "Instandhalten + staendig verbessern (objektive Messungen)") lief der
# Text weit ueber die eigene Box hinaus und ueberlappte Nachbarknoten/die Mittelbeschriftung.
# Empirisch kalibrierter Wert (Schriftgroesse 6.8pt in dieser Schriftart).
CYCLE_SUB_PX_PER_CHAR = 3.3
CYCLE_SUB_LINE_HEIGHT = 7.5


def _esc(text) -> str:
    return html.escape(str(text), quote=True)


def _wobble(inner: str, filt: str = "wob") -> str:
    return f'<g filter="url(#{filt})">{inner}</g>'


def _wrap(template: str, figure, svg_inner: str, width_class: str = "") -> str:
    cls = f"sk {width_class}".strip()
    return f'<div class="sketch-block" data-sketch="{_esc(template)}">{svg_inner}</div>'


def render_stack(block: dict) -> str:
    """Vertikale Ebenen mit Pfeilen dazwischen (z.B. Informationen -> Daten -> Signale)."""
    items = block.get("items") or []
    box_h, gap, top, side = 28, 14, 6, 40
    width = 300
    box_w = width - 2 * side
    n = max(len(items), 1)
    height = top + n * box_h + (n - 1) * gap + top
    rects, texts, arrows = [], [], []
    for i, item in enumerate(items):
        y = top + i * (box_h + gap)
        fill = FILL_CYCLE[i % len(FILL_CYCLE)]
        rects.append(f'<rect class="stroke {fill}" x="{side}" y="{y}" width="{box_w}" height="{box_h}" rx="6"/>')
        cx = width / 2
        title = _esc(item.get("title", ""))
        sub = _esc(item.get("sub", ""))
        texts.append(f'<text x="{cx}" y="{y + 12}" text-anchor="middle" class="st" font-size="12">{title}</text>')
        if sub:
            texts.append(f'<text x="{cx}" y="{y + 23}" text-anchor="middle" font-size="7.5">{sub}</text>')
        if i > 0:
            prev_bottom = top + (i - 1) * (box_h + gap) + box_h
            arrows.append(
                f'<path class="stroke thin" d="M{cx} {prev_bottom + 2} L{cx} {y - 2} '
                f'M{cx - 3} {y - 7} L{cx} {y - 1} L{cx + 3} {y - 7}"/>'
            )
    figure = block.get("figure")
    caption = f'<text x="2" y="{height - 4}" class="cap">Abb. {_esc(figure)}</text>' if figure is not None else ""
    svg = (
        f'<svg class="sk w75" viewBox="0 0 {width} {height}">'
        f'{_wobble("".join(rects) + "".join(arrows))}{"".join(texts)}{caption}</svg>'
    )
    return _wrap("stack", figure, svg)


def render_layers(block: dict) -> str:
    """Schichtenmodell (z.B. TCP/IP-Stack) mit optionaler Seitenannotation je Schicht."""
    items = block.get("items") or []
    n = max(len(items), 1)
    band_h, gap, top, left = 24, 6, 2, 2
    band_w = 200
    figure = block.get("figure")
    caption_space = 12 if figure is not None else 0
    height = top + n * (band_h + gap) + caption_space
    rects, texts, annos = [], [], []
    for i, item in enumerate(items):
        y = top + i * (band_h + gap)
        fill = FILL_CYCLE[i % len(FILL_CYCLE)]
        rects.append(f'<rect class="stroke {fill}" x="{left}" y="{y}" width="{band_w}" height="{band_h}" rx="4"/>')
        title = _esc(item.get("title", ""))
        sub = _esc(item.get("sub", ""))
        texts.append(f'<text x="{left + 6}" y="{y + 10}" class="st" font-size="9">{title}</text>')
        if sub:
            texts.append(f'<text x="{left + 6}" y="{y + 21}" font-size="7.5">{sub}</text>')
        anno = _esc(item.get("anno", ""))
        if anno:
            annos.append(f'<text x="{left + band_w + 8}" y="{y + 12}" font-size="7" class="cap">{anno}</text>')
        if i > 0:
            mid_x = left + band_w / 2
            prev_bottom = top + (i - 1) * (band_h + gap) + band_h
            annos.append(
                f'<path class="stroke thin" d="M{mid_x} {prev_bottom} L{mid_x} {y} '
                f'M{mid_x - 3} {y - 6} L{mid_x} {y} L{mid_x + 3} {y - 6}"/>'
            )
    caption = f'<text x="2" y="{height - 3}" class="cap">Abb. {_esc(figure)}</text>' if figure is not None else ""
    svg = (
        f'<svg class="sk w90" viewBox="0 0 300 {height}">'
        f'{_wobble("".join(rects) + "".join(a for a in annos if a.startswith("<path")))}'
        f'{"".join(texts)}{"".join(a for a in annos if not a.startswith("<path"))}{caption}</svg>'
    )
    return _wrap("layers", figure, svg)


def render_cycle(block: dict) -> str:
    """3-5 Knoten im Kreis, je in einer Box, mit Pfeil-Boegen dazwischen (z.B.
    Praevention/Detektion/Reaktion) -- Boxen + Pfeilspitzen wie in der Referenz."""
    import math

    items = block.get("items") or []
    n = max(len(items), 1)
    cx, cy, r = 150, 62, 48
    box_h = 24
    positions = []
    for i in range(n):
        angle = -math.pi / 2 + i * (2 * math.pi / n)
        positions.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

    box_widths = [max(60, 8 * len(item.get("title", ""))) for item in items]

    boxes, texts, paths = [], [], []
    max_sub_lines = 1
    for i, item in enumerate(items):
        x, y = positions[i]
        title = _esc(item.get("title", ""))
        sub_raw = item.get("sub", "")
        box_w = box_widths[i]
        fill = FILL_CYCLE[i % len(FILL_CYCLE)]
        boxes.append(
            f'<rect class="stroke {fill}" x="{x - box_w / 2:.0f}" y="{y - box_h / 2:.0f}" '
            f'width="{box_w:.0f}" height="{box_h}" rx="6"/>'
        )
        texts.append(f'<text x="{x:.0f}" y="{y + 4:.0f}" text-anchor="middle" class="st" font-size="11">{title}</text>')
        if sub_raw:
            # Auf die Box-Breite umbrechen statt als eine lange Zeile zu rendern -- sonst
            # laeuft der Text bei laengeren Saetzen ueber Nachbarknoten/Mittelbeschriftung
            # hinweg (siehe Modul-Docstring, CYCLE_SUB_PX_PER_CHAR).
            chars_per_line = max(10, int(box_w / CYCLE_SUB_PX_PER_CHAR))
            lines = textwrap.wrap(sub_raw, width=chars_per_line) or [sub_raw]
            max_sub_lines = max(max_sub_lines, len(lines))
            start_y = y + box_h / 2 + 9
            for li, line in enumerate(lines):
                line_y = start_y + li * CYCLE_SUB_LINE_HEIGHT
                texts.append(f'<text x="{x:.0f}" y="{line_y:.0f}" text-anchor="middle" font-size="6.8">{_esc(line)}</text>')

    for i in range(n):
        x1, y1 = positions[i]
        x2, y2 = positions[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy) or 1
        ux, uy = dx / dist, dy / dist
        # Clearance je Knoten anhand seiner EIGENEN Box-Diagonale (nicht nur box_h) --
        # sonst verschwinden Boegen unter breiten Boxen (z.B. laengere Titel).
        clear1 = math.hypot(box_widths[i] / 2, box_h / 2) * 0.85
        clear2 = math.hypot(box_widths[(i + 1) % n] / 2, box_h / 2) * 0.85
        start_x, start_y = x1 + ux * clear1, y1 + uy * clear1
        end_x, end_y = x2 - ux * clear2, y2 - uy * clear2
        mid_x, mid_y = (start_x + end_x) / 2, (start_y + end_y) / 2
        out_x, out_y = mid_x - cx, mid_y - cy
        out_dist = math.hypot(out_x, out_y) or 1
        bow_x = mid_x + out_x / out_dist * 16
        bow_y = mid_y + out_y / out_dist * 16
        arrow_angle = math.atan2(end_y - bow_y, end_x - bow_x)
        a1x = end_x - 6 * math.cos(arrow_angle - 0.4)
        a1y = end_y - 6 * math.sin(arrow_angle - 0.4)
        a2x = end_x - 6 * math.cos(arrow_angle + 0.4)
        a2y = end_y - 6 * math.sin(arrow_angle + 0.4)
        paths.append(
            f'<path class="stroke" d="M{start_x:.0f} {start_y:.0f} Q{bow_x:.0f} {bow_y:.0f} '
            f'{end_x:.0f} {end_y:.0f} M{a1x:.0f} {a1y:.0f} L{end_x:.0f} {end_y:.0f} L{a2x:.0f} {a2y:.0f}"/>'
        )

    figure = block.get("figure")
    caption = f'<text x="{cx}" y="{cy}" text-anchor="middle" class="cap" font-size="9">Abb. {_esc(figure)}</text>' if figure is not None else ""
    # Zusaetzliche Hoehe fuer mehrzeilige "sub"-Labels einrechnen (siehe oben) -- betrifft vor
    # allem den untersten Knoten, dessen Text sonst ueber den festen 118px-Rahmen hinauslief.
    extra_height = (max_sub_lines - 1) * CYCLE_SUB_LINE_HEIGHT
    total_height = 118 + extra_height + (4 if extra_height else 0)
    svg = (
        f'<svg class="sk w75" viewBox="0 0 300 {total_height:.0f}">'
        f'{_wobble("".join(paths) + "".join(boxes))}{"".join(texts)}{caption}</svg>'
    )
    return _wrap("cycle", figure, svg)


def render_rings(block: dict) -> str:
    """Konzentrische Kreise (z.B. Individual-/Privat-/Intimsphaere)."""
    items = block.get("items") or []
    n = max(len(items), 1)
    cx, r_max, bottom = 75, 70, 145
    shrink = 0.74  # jeder Ring ~74% des vorherigen Radius, wie in der Referenz
    ring_fills = ["fla", "fl", "fw"]
    circles, labels = [], []
    for i, item in enumerate(items):
        r = r_max * (shrink ** i)
        cy = bottom - r
        fill = ring_fills[i % len(ring_fills)]
        circles.append(f'<circle class="stroke {fill}" cx="{cx}" cy="{cy:.0f}" r="{r:.0f}"/>')
        label = _esc(item.get("title", ""))
        text_y = cy - r + 15
        labels.append(f'<text x="{cx}" y="{text_y:.0f}" text-anchor="middle" class="st" font-size="10">{label}</text>')
    figure = block.get("figure")
    caption = f'<text x="4" y="14" class="cap">Abb. {_esc(figure)}</text>' if figure is not None else ""
    # Groesster Kreis zuerst zeichnen, kleinere Ringe danach obenauf -- sonst verdecken die
    # aeusseren Kreise die inneren.
    svg = (
        f'<svg class="sk" viewBox="0 0 150 150" style="width:40mm;flex:none">'
        f'{_wobble("".join(circles))}{"".join(labels)}{caption}</svg>'
    )
    return _wrap("rings", figure, svg)


def render_triangle(block: dict) -> str:
    """Ist/Soll/Ideal-Dreieck mit 3 Eckenlabels (z.B. Vertraulichkeit/Integritaet/Verfuegbarkeit)."""
    items = block.get("items") or []
    corners = [item.get("title", "") for item in items[:3]] + [""] * max(0, 3 - len(items))
    levels = [item.get("sub", "") for item in items[:1]]
    svg = (
        '<svg class="sk" viewBox="0 0 160 140" style="width:50mm;flex:none">'
        + _wobble(
            '<path class="stroke fl" d="M80 8 L152 128 L8 128 Z"/>'
            '<path class="stroke thin" d="M80 38 L128 118 L32 118 Z" fill="#c8b6ff"/>'
            '<path class="stroke thin" d="M78 66 L108 108 L52 104 Z" fill="#fff08f"/>'
        )
        + f'<text x="80" y="6" text-anchor="middle" class="st" font-size="9">{_esc(corners[0])}</text>'
        + f'<text x="20" y="138" text-anchor="middle" class="st" font-size="9">{_esc(corners[1])}</text>'
        + f'<text x="140" y="138" text-anchor="middle" class="st" font-size="9">{_esc(corners[2])}</text>'
        + '<text x="80" y="58" text-anchor="middle" class="cap">Ideal</text>'
        + '<text x="80" y="80" text-anchor="middle" class="cap">Soll</text>'
        + '<text x="80" y="102" text-anchor="middle" class="cap">Ist</text>'
        + (f'<text x="2" y="16" class="cap">Abb. {_esc(block.get("figure"))}</text>' if block.get("figure") is not None else "")
        + "</svg>"
    )
    return _wrap("triangle", block.get("figure"), svg)


def render_timeline(block: dict) -> str:
    """Horizontale Zeitleiste mit Datumspunkten und Beschriftung."""
    items = block.get("items") or []
    n = max(len(items), 1)
    left, right, y = 20, 280, 40
    step = (right - left) / max(n - 1, 1)
    dots, texts = [], []
    for i, item in enumerate(items):
        x = left + i * step
        fill = "fla" if i % 2 else "fw"
        dots.append(f'<circle class="stroke {fill}" cx="{x:.0f}" cy="{y}" r="5.5"/>')
        date = _esc(item.get("title", ""))
        texts.append(f'<text x="{x:.0f}" y="{y - 14}" text-anchor="middle" class="st" font-size="9">{date}</text>')
        sub = item.get("sub", "")
        for j, line in enumerate(str(sub).split("|")[:3]):
            texts.append(f'<text x="{x:.0f}" y="{y + 16 + j * 8}" text-anchor="middle" font-size="6.5">{_esc(line)}</text>')
    figure = block.get("figure")
    caption = f'<text x="150" y="90" text-anchor="middle" class="cap" font-size="6.5">Abb. {_esc(figure)}</text>' if figure is not None else ""
    baseline = f'<path class="stroke" d="M{left - 12} {y} C{left + 60} {y - 2},{right - 60} {y + 2},{right + 12} {y}"/>'
    svg = (
        f'<svg class="sk" viewBox="0 0 300 92">'
        f'{_wobble(baseline + "".join(dots))}'
        f'{"".join(texts)}{caption}</svg>'
    )
    return _wrap("timeline", figure, svg)


def render_flow(block: dict) -> str:
    """Kette aus Boxen mit Pfeilen (z.B. Boot-Vorgang)."""
    items = block.get("items") or []
    n = max(len(items), 1)
    width, height, gap, box_h, y = 300, 40, 8, 24, 8
    total_gap = gap * (n - 1)
    box_w = (width - total_gap) / n
    rects, texts, arrows = [], [], []
    for i, item in enumerate(items):
        x = i * (box_w + gap)
        fill = "fl" if i == n // 2 else "fw"
        rects.append(f'<rect class="stroke {fill}" x="{x:.0f}" y="{y}" width="{box_w:.0f}" height="{box_h}" rx="5"/>')
        title = _esc(item.get("title", ""))
        texts.append(f'<text x="{x + box_w / 2:.0f}" y="{y + box_h / 2 + 3:.0f}" text-anchor="middle" font-size="8.5">{title}</text>')
        if i > 0:
            ax = x - gap
            arrows.append(
                f'<path class="stroke" d="M{ax:.0f} {y + box_h / 2:.0f} L{x - 2:.0f} {y + box_h / 2:.0f} '
                f'M{x - 6:.0f} {y + box_h / 2 - 4:.0f} L{x - 1:.0f} {y + box_h / 2:.0f} L{x - 6:.0f} {y + box_h / 2 + 4:.0f}"/>'
            )
    figure = block.get("figure")
    caption = f'<text x="2" y="{height - 2}" class="cap">Abb. {_esc(figure)}</text>' if figure is not None else ""
    svg = (
        f'<svg class="sk w85" viewBox="0 0 {width} {height}">'
        f'{_wobble("".join(rects) + "".join(arrows))}{"".join(texts)}{caption}</svg>'
    )
    return _wrap("flow", figure, svg)


def render_image(block: dict, image_path=None) -> str:
    """Echte extrahierte Abbildung statt nachgezeichneter Skizze.

    image_path wird vom Aufrufer (render_sketch) ueber caption_key()/caption_text_key()
    gematcht -- das JSON traegt nur die Bildunterschrift, keinen Dateipfad (die KI kennt den
    tatsaechlichen Dateinamen nicht).
    """
    caption = _esc(block.get("caption", ""))
    if image_path is not None:
        inner = f'<figure><img src="{_esc(image_path)}" alt="{caption}" loading="lazy"><figcaption class="abb">{caption}</figcaption></figure>'
    else:
        inner = (
            f'<div class="box" style="border:1.6px dashed var(--ink)">'
            f'<span class="label">Bild fehlt</span>{caption}</div>'
        )
    return f'<div class="sketch-block" data-sketch="image">{inner}</div>'


_RENDERERS = {
    "stack": render_stack,
    "cycle": render_cycle,
    "layers": render_layers,
    "rings": render_rings,
    "triangle": render_triangle,
    "timeline": render_timeline,
    "flow": render_flow,
}


def render(block: dict, image_resolver=None) -> str:
    """Dispatcht auf die passende render_*-Funktion. `image_resolver(caption, figure) ->
    str|None` wird nur fuer template == "image" gebraucht -- `figure` (die Zahl aus dem
    Schema) ist der zuverlaessigere Match-Schluessel, `caption` nur der Fallback, falls die
    KI kein "figure"-Feld gesetzt hat."""
    template = block.get("template", "image")
    if template == "image":
        image_path = image_resolver(block.get("caption"), block.get("figure")) if image_resolver else None
        return render_image(block, image_path)
    renderer = _RENDERERS.get(template, render_stack)
    return renderer(block)
