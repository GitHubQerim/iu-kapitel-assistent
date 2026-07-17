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

Mehrere PDFs als Input sind möglich, um Kapitel aus verschiedenen Quellen zu einer Zusammenfassung bzw. einem Deck zu kombinieren. Seiten mit eingebetteten Bildern (Diagramme, Grafiken) werden automatisch extrahiert. Bei Karteikarten bittet der Prompt die KI, zu jeder erkannten Abbildung eine echte Verständnisfrage zu schreiben (nicht nur die Bildunterschrift als Frage) — das passende Bild wird dann automatisch an genau diese Karte gehängt. Nur Abbildungen, zu denen keine Karte erstellt wurde, bekommen als Fallback eine einfache Bild-Karte, damit nichts verloren geht. Der Anki-Deck-Name lässt sich über `--deck` setzen (z. B. `--deck "DLBMIUID01-01::Kapitel 8"`, mit `::` für verschachtelte Decks in Anki); ohne Angabe wird der Ordnername verwendet.

Falls die Antwort aus dem Chat-Tool kein valides JSON ist (z. B. weil ein Codeblock oder ein einleitender Satz mitkopiert wurde), bricht der Befehl nicht ab: der Fehler wird angezeigt, der Prompt bleibt in der Zwischenablage, und man kann die Antwort korrigieren und einfach erneut Enter drücken.

### GUI

```bash
python3 gui.py
```

Natives Fenster (via [pywebview](https://pywebview.flowrl.com/), Oberfläche in `ui.html`) statt Pfade abzutippen: ein oder mehrere Kapitel-PDFs per Datei-Dialog wählen, Modus (Zusammenfassung/Karteikarten) umschalten, Ausgabedatei wählen, dann "Prompt kopieren" → in ein Chat-Tool einfügen → "Antwort einlesen" klicken. Im Karteikarten-Modus erscheint zusätzlich ein Deck-Name-Feld (vorbelegt mit `Modulcode::Kapitelname`), damit sich die Decks in Anki sauber nach Modul/Kapitel verschachteln lassen. Der (i)-Button oben rechts zeigt den Ablauf als Erinnerung. Bei einer fehlerhaften Antwort einfach im Chat-Tool korrigieren und erneut auf "Antwort einlesen" klicken; nach Erfolg öffnet "Im Finder zeigen" die fertige Datei direkt im Finder.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
