import json
from pathlib import Path

import jsonschema

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lektion1_sketch.json"
SCHEMA_PATH = Path(__file__).parent.parent / "schema" / "sketch_summary.schema.json"


def test_fixture_matches_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


def test_fixture_covers_all_sketch_templates():
    from render.sketch.svg_templates import TEMPLATES

    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    used = {b["template"] for b in data["blocks"] if b.get("type") == "sketch"}
    missing = set(TEMPLATES) - used
    assert not missing, f"Fixture deckt nicht alle Sketch-Templates ab: {missing}"


def test_schema_rejects_missing_required_field():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    del data["learning_goals"]
    try:
        jsonschema.validate(data, schema)
        assert False, "hätte fehlschlagen müssen"
    except jsonschema.ValidationError:
        pass
