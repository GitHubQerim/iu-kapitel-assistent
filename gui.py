#!/usr/bin/env python3
"""Kleine Desktop-Oberfläche für kapitel_assistent.py."""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from kapitel_assistent import (
    FLASHCARDS_PROMPT,
    SUMMARY_PROMPT,
    build_content,
    copy_to_clipboard,
    is_unchanged_prompt,
    parse_flashcards,
    read_clipboard,
    save_chapter_images,
)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Kapitel-Assistent")
        self.geometry("680x520")
        self.pdf_paths = []
        self.mode = tk.StringVar(value="summary")
        self.output_path = tk.StringVar()
        self._pending = None  # (pdf_paths, content, image_pages) während auf Antwort gewartet wird
        self._last_prompt = None
        self._build()

    def _build(self):
        pad = {"padx": 10, "pady": 6}

        frame_files = tk.Frame(self)
        frame_files.pack(fill="x", **pad)
        tk.Button(frame_files, text="Kapitel-PDF(s) wählen...", command=self.pick_files).pack(side="left")
        self.files_label = tk.Label(frame_files, text="Keine Datei gewählt", anchor="w")
        self.files_label.pack(side="left", fill="x", expand=True, padx=8)

        frame_mode = tk.Frame(self)
        frame_mode.pack(fill="x", **pad)
        tk.Label(frame_mode, text="Modus:").pack(side="left")
        tk.Radiobutton(frame_mode, text="Zusammenfassung", variable=self.mode, value="summary",
                        command=self._update_default_output).pack(side="left", padx=6)
        tk.Radiobutton(frame_mode, text="Karteikarten", variable=self.mode, value="flashcards",
                        command=self._update_default_output).pack(side="left", padx=6)

        frame_out = tk.Frame(self)
        frame_out.pack(fill="x", **pad)
        tk.Label(frame_out, text="Ausgabedatei:").pack(side="left")
        tk.Entry(frame_out, textvariable=self.output_path).pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(frame_out, text="Wählen...", command=self.pick_output).pack(side="left")

        instructions = (
            "Ablauf:  1) Prompt kopieren  →  2) in ChatGPT/Claude/Gemini (o.ä.) einfügen & abschicken\n"
            "→  3) dort die Antwort kopieren  →  4) hierher zurück und auf 'Antwort einlesen' klicken."
        )
        tk.Label(self, text=instructions, justify="left", fg="#888").pack(fill="x", padx=10, pady=(0, 4))

        style = ttk.Style(self)
        style.configure("Assist.TButton", font=("SF Pro Text", 12, "bold"), padding=(16, 6))

        frame_buttons = tk.Frame(self)
        frame_buttons.pack(pady=10)
        ttk.Button(frame_buttons, text="1. Prompt kopieren", style="Assist.TButton",
                   command=self.copy_prompt).pack(side="left", padx=6)
        ttk.Button(frame_buttons, text="2. Antwort einlesen", style="Assist.TButton",
                   command=self.read_response).pack(side="left", padx=6)

        self.log = scrolledtext.ScrolledText(self, state="disabled", font=("Menlo", 11))
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _update_default_output(self):
        if not self.pdf_paths:
            return
        stem = Path(self.pdf_paths[0]).stem
        ext = "apkg" if self.mode.get() == "flashcards" else "md"
        self.output_path.set(str(Path(self.pdf_paths[0]).parent / f"{stem}.{ext}"))

    def pick_files(self):
        paths = filedialog.askopenfilenames(filetypes=[("PDF-Dateien", "*.pdf")])
        if paths:
            self.pdf_paths = list(paths)
            names = ", ".join(Path(p).name for p in self.pdf_paths)
            self.files_label.config(text=names)
            self._update_default_output()

    def pick_output(self):
        ext = "apkg" if self.mode.get() == "flashcards" else "md"
        path = filedialog.asksaveasfilename(defaultextension=f".{ext}", filetypes=[(ext.upper(), f"*.{ext}")])
        if path:
            self.output_path.set(path)

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def copy_prompt(self):
        if not self.pdf_paths:
            messagebox.showwarning("Fehlt", "Bitte zuerst ein oder mehrere Kapitel-PDFs wählen.")
            return
        pdf_paths = [Path(p) for p in self.pdf_paths]
        content, image_pages = build_content(pdf_paths)
        self._pending = (pdf_paths, content, image_pages)

        template = FLASHCARDS_PROMPT if self.mode.get() == "flashcards" else SUMMARY_PROMPT
        prompt = template.format(content=content)
        self._last_prompt = prompt
        copy_to_clipboard(prompt)
        self.write_log("Prompt in die Zwischenablage kopiert. Füge ihn in ChatGPT/Claude/Gemini (o.ä.) ein, "
                        "schick ihn ab, und kopiere danach NUR die Antwort zurück.")

    def read_response(self):
        if not self._pending:
            messagebox.showwarning("Fehlt", "Bitte zuerst auf '1. Prompt kopieren' klicken.")
            return
        if not self.output_path.get().strip():
            messagebox.showwarning("Fehlt", "Bitte eine Ausgabedatei wählen.")
            return

        pdf_paths, content, image_pages = self._pending
        response = read_clipboard().strip()
        if not response:
            self.write_log("Zwischenablage ist leer. Antwort im Chat-Tool kopieren und erneut klicken.")
            return
        if is_unchanged_prompt(response, self._last_prompt):
            self.write_log("In der Zwischenablage steht noch der Prompt selbst, nicht die Antwort des Chat-Tools.")
            self.write_log("Erst den Prompt dort einfügen & abschicken, die Antwort abwarten, DIE ANTWORT kopieren "
                            "– dann hier erneut klicken.")
            return

        out_path = Path(self.output_path.get())
        try:
            if self.mode.get() == "flashcards":
                self._build_flashcards(response, pdf_paths, image_pages, out_path)
            else:
                self._build_summary(response, image_pages, out_path)
        except ValueError as exc:
            self.write_log(f"Antwort konnte nicht verarbeitet werden: {exc}")
            self.write_log("Korrigiere die Antwort im Chat-Tool, kopiere sie neu und klicke wieder auf '2. Antwort einlesen'.")
            return

        self.write_log(f"Fertig: {out_path}")
        self._pending = None

    def _build_summary(self, response, image_pages, out_path: Path):
        out_path.write_text(response, encoding="utf-8")
        saved_images = save_chapter_images(image_pages, out_path.parent / f"{out_path.stem}_bilder")
        if saved_images:
            with out_path.open("a", encoding="utf-8") as f:
                f.write("\n\n## Bilder aus diesem Kapitel\n\n")
                for pdf_path, page_num, img_path in saved_images:
                    rel = img_path.relative_to(out_path.parent)
                    f.write(f"![{pdf_path.stem} Seite {page_num}]({rel})\n\n")
            self.write_log(f"{len(saved_images)} Bild(er) mit gespeichert.")

    def _build_flashcards(self, response, pdf_paths, image_pages, out_path: Path):
        import genanki

        cards = parse_flashcards(response)

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
        for pdf_path, page_num, img_path in saved_images:
            deck.add_note(
                genanki.Note(
                    model=model,
                    fields=[f"Bild – {pdf_path.stem}, Seite {page_num}", f'<img src="{img_path.name}">'],
                )
            )
            media_files.append(str(img_path))

        package = genanki.Package(deck)
        package.media_files = media_files
        package.write_to_file(str(out_path))

        self.write_log(f"{len(cards)} Karteikarte(n) + {len(saved_images)} Bild-Karte(n).")


if __name__ == "__main__":
    App().mainloop()
