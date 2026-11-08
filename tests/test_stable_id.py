import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_stable_id_deterministic_within_process():
    import kapitel_assistent as ka

    assert ka.stable_id("DLBLOFUI01-02::Kapitel 1") == ka.stable_id("DLBLOFUI01-02::Kapitel 1")


def test_stable_id_differs_for_different_names():
    import kapitel_assistent as ka

    assert ka.stable_id("Kapitel 1") != ka.stable_id("Kapitel 2")


def test_stable_id_independent_of_hash_seed():
    """Regression guard: build_flashcards_deck() used Pythons hash() before, which is
    randomized per process (PYTHONHASHSEED) -- re-generating the same deck in a later
    run produced a different deck_id, so Anki couldn't recognize it as an update."""
    script = (
        "import sys; sys.path.insert(0, %r); import kapitel_assistent as ka; "
        "print(ka.stable_id('DLBLOFUI01-02::Kapitel 1'))" % str(ROOT)
    )
    results = set()
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                              env=env, check=True)
        results.add(out.stdout.strip())
    assert len(results) == 1, f"stable_id() schwankt je nach PYTHONHASHSEED: {results}"
