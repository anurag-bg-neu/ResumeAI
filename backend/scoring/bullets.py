"""
bullets.py
----------
The one definition of "which résumé lines get scored". The TF-IDF scorer, the
semantic scorer and the gap analysis all read bullets through here, so their
scores always cover the same set of text.
"""

from __future__ import annotations

from collections.abc import Iterator

SCORED_SECTIONS: tuple[str, ...] = ("experience", "projects")


def iter_bullets(resume: dict) -> Iterator[tuple[str, int, int, str]]:
    """Yield (section, entry_index, bullet_index, text) for every scored bullet."""
    for section in SCORED_SECTIONS:
        for entry_idx, entry in enumerate(resume["sections"].get(section, [])):
            for bullet_idx, text in enumerate(entry.get("bullets", [])):
                yield section, entry_idx, bullet_idx, text
