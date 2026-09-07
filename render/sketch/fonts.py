"""Base64-Einbettung der Sketch-Lernblatt-Fonts, damit die erzeugte HTML-Datei offline
funktioniert (keine Google-Fonts-Verbindung wie beim klassischen Summary-Renderer).

Die .woff2-Dateien liegen unter render/sketch/fonts/ (aus github.com/google/fonts, OFL bzw.
Apache-lizenziert, lokal mit fonttools nach woff2 konvertiert).
"""
import base64
from functools import lru_cache
from pathlib import Path

FONTS_DIR = Path(__file__).parent / "fonts"

FONT_FACES = [
    ("Kalam", 300, "normal", "Kalam-Light.woff2"),
    ("Kalam", 400, "normal", "Kalam-Regular.woff2"),
    ("Kalam", 700, "normal", "Kalam-Bold.woff2"),
    ("Caveat", "400 700", "normal", "Caveat-Variable.woff2"),
    ("Permanent Marker", 400, "normal", "PermanentMarker-Regular.woff2"),
]


def _font_face_rule(family: str, weight, style: str, filename: str) -> str:
    data = (FONTS_DIR / filename).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return (
        f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:{style};"
        f"font-display:swap;src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
    )


@lru_cache(maxsize=1)
def build_font_face_css() -> str:
    """Baut die kompletten @font-face-Regeln als ein CSS-String (base64-embedded).

    Die Fonts aendern sich nie zur Laufzeit -- gecacht, damit nicht bei jedem render_sketch()
    erneut ~470 KB Font-Dateien gelesen und base64-kodiert werden."""
    return "\n".join(_font_face_rule(*face) for face in FONT_FACES)
