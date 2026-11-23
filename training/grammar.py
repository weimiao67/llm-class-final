"""Phrase grammar: seeded expansion of sentence shapes with interchangeable parts.

A shape such as ``"{how} {metric} in {place} {change} {period}?"`` is expanded by replacing each
``{part}`` with one of its alternatives (which may contain further parts). Slot values such as the
city, state, and period are passed in directly, so wording can never change the meaning: the gold
plan is built from the same slot values.
"""

from __future__ import annotations

import random
import re

_PART = re.compile(r"\{(\w+)\}")
MAX_DEPTH = 8


class Grammar:
    def __init__(self, parts: dict[str, list[str]]):
        self.parts = parts

    def expand(self, text: str, rng: random.Random, slots: dict[str, str], _depth: int = 0) -> str:
        if _depth > MAX_DEPTH:
            raise RecursionError(f"grammar nests deeper than {MAX_DEPTH}: {text!r}")

        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name in slots:
                return str(slots[name])
            if name not in self.parts:
                raise KeyError(f"unknown grammar part {{{name}}}")
            return self.expand(rng.choice(self.parts[name]), rng, slots, _depth + 1)

        return _PART.sub(replace, text)

    def sentence(self, shape: str, rng: random.Random, slots: dict[str, str]) -> str:
        return tidy(self.expand(shape, rng, slots))


def tidy(text: str) -> str:
    """Collapse spaces left by empty parts, fix spacing before punctuation, capitalize."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([?.,!:;])", r"\1", text)
    text = re.sub(r"([?.!])\1+", r"\1", text)
    return text[:1].upper() + text[1:] if text else text


def add_noise(text: str, rng: random.Random) -> str:
    """Light, meaning-preserving noise: casing, trailing punctuation, terse abbreviations."""
    if rng.random() < 0.15:
        text = text.lower()
    if rng.random() < 0.2:
        text = text.rstrip("?.!")
    if rng.random() < 0.08:
        text = text.replace("year-over-year", "yoy").replace("Year-over-year", "YoY")
    return text
