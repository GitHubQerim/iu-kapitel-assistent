# IU Kapitel-Assistent

Erzeugt aus einem oder mehreren Kapitel-PDFs eines IU-Studienskripts entweder eine Wiedereinstiegs-Zusammenfassung oder ein Anki-Karteikarten-Deck.

Kein eigener API-Key nötig: Das Tool kopiert einen fertigen Prompt in die Zwischenablage, du fügst ihn in ein beliebiges KI-Chat-Tool ein (ChatGPT, Claude, Gemini, ...), kopierst die Antwort zurück in die Zwischenablage und drückst Enter. Das funktioniert mit jedem bestehenden Pro-Abo, ohne separate API-Kosten.

Passt als Ergänzung zu [iu-kapitel-splitter](https://github.com/GitHubQerim/iu-kapitel-splitter), das ein IU-Course-Book zunächst in einzelne Kapitel-PDFs zerlegt — kann aber auch mit jedem anderen PDF genutzt werden, das eine einzelne Lektion/ein einzelnes Kapitel enthält.

## Installation

```bash
python3 -m pip install -r requirements.txt
```

## Nutzung

```bash
# Zusammenfassung (Markdown, inkl. Bildern aus dem Kapitel)
python3 kapitel_assistent.py summary kapitel_1_einfuehrung.pdf --out zusammenfassung.md

# Anki-Karteikarten (.apkg, inkl. Bild-Karten für Diagramme/Grafiken)
python3 kapitel_assistent.py flashcards kapitel_1_einfuehrung.pdf --out karteikarten.apkg
```

Ablauf: Prompt wird automatisch in die Zwischenablage kopiert → in ein KI-Chat-Tool einfügen → Antwort kopieren → im Terminal Enter drücken. Das Tool liest die Antwort aus der Zwischenablage und baut daraus die Ausgabedatei.

Mehrere PDFs als Input sind möglich, um Kapitel aus verschiedenen Quellen zu einer Zusammenfassung bzw. einem Deck zu kombinieren. Seiten mit eingebetteten Bildern (Diagramme, Grafiken) werden automatisch extrahiert und als eigene Karten bzw. am Ende der Zusammenfassung angehängt, damit nichts Wichtiges verloren geht.

Falls die Antwort aus dem Chat-Tool kein valides JSON ist (z. B. weil ein Codeblock oder ein einleitender Satz mitkopiert wurde), bricht der Befehl nicht ab: der Fehler wird angezeigt, der Prompt bleibt in der Zwischenablage, und man kann die Antwort korrigieren und einfach erneut Enter drücken.

### GUI

```bash
python3 gui.py
```

Datei-Dialog statt Pfade abzutippen: ein oder mehrere Kapitel-PDFs wählen, Modus (Zusammenfassung/Karteikarten) auswählen, Ausgabedatei wählen, dann nacheinander auf "1. Prompt kopieren" und nach dem Einfügen der Chat-Antwort auf "2. Antwort einlesen" klicken. Bei einer fehlerhaften Antwort einfach im Chat-Tool korrigieren und erneut auf "2. Antwort einlesen" klicken.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
