"""Documentation links: every relative link in the README and docs/ points to a real file."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), ROOT / "training" / "README.md",
        ROOT / "evaluation" / "README.md"]  # fmt: skip
LINK = re.compile(r"\]\(([^)\s]+)\)")


def relative_links(doc: Path) -> list[str]:
    text = re.sub(r"```.*?```", "", doc.read_text(), flags=re.S)  # skip code blocks
    return [
        target.split("#", 1)[0]
        for target in LINK.findall(text)
        if not re.match(r"[a-z]+:", target) and not target.startswith("#")
    ]


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(doc):
    missing = [t for t in relative_links(doc) if t and not (doc.parent / t).exists()]
    assert not missing, f"{doc.name} links to missing files: {missing}"


def test_readme_indexes_every_doc():
    readme = (ROOT / "README.md").read_text()
    for doc in sorted((ROOT / "docs").glob("*.md")):
        assert f"docs/{doc.name}" in readme, f"README doesn't link docs/{doc.name}"
