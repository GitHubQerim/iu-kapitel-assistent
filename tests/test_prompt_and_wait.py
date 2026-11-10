import pytest

import kapitel_assistent as ka


def _clipboard_forbidden(monkeypatch):
    """Lässt den Test fehlschlagen, falls doch auf die Zwischenablage zugegriffen wird --
    --prompt-out/--response-file sollen genau das vermeiden."""
    def boom(*_a, **_kw):
        raise AssertionError("Zwischenablage hätte in diesem Modus nicht benutzt werden dürfen")

    monkeypatch.setattr(ka, "copy_to_clipboard", boom)
    monkeypatch.setattr(ka, "read_clipboard", boom)


def test_prompt_out_writes_prompt_and_exits_without_clipboard(tmp_path, monkeypatch):
    _clipboard_forbidden(monkeypatch)
    prompt_out = tmp_path / "prompt.txt"

    with pytest.raises(SystemExit) as exc:
        ka.prompt_and_wait("Mein Prompt", "Test", prompt_out=prompt_out)

    assert exc.value.code == 0
    assert prompt_out.read_text(encoding="utf-8") == "Mein Prompt"


def test_response_file_reads_and_parses_without_clipboard(tmp_path, monkeypatch):
    _clipboard_forbidden(monkeypatch)
    response_file = tmp_path / "response.json"
    response_file.write_text('[{"front": "F", "back": "B"}]', encoding="utf-8")

    cards = ka.prompt_and_wait("irrelevant", "Test", parse_fn=ka.parse_flashcards,
                                response_file=response_file)

    assert cards == [{"front": "F", "back": "B"}]


def test_response_file_rejects_empty_file(tmp_path, monkeypatch):
    _clipboard_forbidden(monkeypatch)
    response_file = tmp_path / "empty.txt"
    response_file.write_text("   ", encoding="utf-8")

    with pytest.raises(SystemExit):
        ka.prompt_and_wait("irrelevant", "Test", response_file=response_file)
