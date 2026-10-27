"""La recette du jalon A ne cite que des tests qui existent (sinon elle se périme en silence)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECETTE = ROOT / "docs" / "recette-jalon-a.md"
REFERENCE = re.compile(r"`(engine/tests/[\w]+\.py)::(test_\w+)`")


def test_every_test_cited_in_the_recette_exists():
    text = RECETTE.read_text(encoding="utf-8")
    references = REFERENCE.findall(text)
    assert len(references) >= 40  # garde-fou : le document est bien lu
    missing = []
    for file, name in references:
        source = (ROOT / file).read_text(encoding="utf-8") if (ROOT / file).exists() else ""
        if not re.search(rf"^(async )?def {name}\b", source, re.MULTILINE):
            missing.append(f"{file}::{name}")
    assert not missing, missing


def test_every_criterion_of_the_spec_is_in_the_recette():
    text = RECETTE.read_text(encoding="utf-8")
    for number in range(1, 13):
        assert re.search(rf"^### {number}\. ", text, re.MULTILINE), f"critère {number} absent"
