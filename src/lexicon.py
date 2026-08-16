"""Surgical, conservative Skyrim entity correction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_WORD = re.compile(r"[\w']+", re.UNICODE)


def _normal(value: str) -> str:
    return " ".join(_WORD.findall(value.casefold()))


def _distance(a: str, b: str) -> int:
    """Damerau-Levenshtein distance, including adjacent transpositions."""
    previous_previous: list[int] | None = None
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            cost = left != right
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + cost))
            if previous_previous is not None and i > 1 and j > 1 and left == b[j - 2] and a[i - 2] == right:
                current[-1] = min(current[-1], previous_previous[j - 2] + cost)
        previous_previous, previous = previous, current
    return previous[-1]


@dataclass(frozen=True)
class Entry:
    canonical: str
    aliases: tuple[str, ...] = ()
    category: str | None = None

    @property
    def forms(self) -> tuple[str, ...]:
        return (self.canonical, *self.aliases)


class SkyrimLexicon:
    def __init__(self, entries: Iterable[Entry] = (), threshold: float = 0.89, margin: float = 0.10):
        self.entries = tuple(entries)
        self.threshold = float(threshold)
        self.margin = float(margin)

    @classmethod
    def load(cls, path: str | Path, *, threshold: float = 0.89, margin: float = 0.10) -> "SkyrimLexicon":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls((), threshold, margin)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid Skyrim lexicon {path}: {exc}") from exc
        if isinstance(raw, dict):
            raw = raw.get("entries", [])
        if not isinstance(raw, list):
            raise ValueError("Skyrim lexicon must be an array or an object with an entries array")
        entries: list[Entry] = []
        seen: set[str] = set()
        for item in raw:
            if isinstance(item, str):
                item = {"canonical": item}
            if not isinstance(item, dict) or not isinstance(item.get("canonical"), str):
                raise ValueError("Each Skyrim lexicon entry requires a string canonical field")
            canonical = item["canonical"].strip()
            key = _normal(canonical)
            if not canonical or not key or key in seen:
                continue
            aliases = item.get("aliases", [])
            if not isinstance(aliases, list) or not all(isinstance(x, str) for x in aliases):
                raise ValueError(f"Aliases for {canonical!r} must be an array of strings")
            seen.add(key)
            entries.append(Entry(canonical, tuple(x.strip() for x in aliases if _normal(x)), item.get("category")))
        return cls(entries, threshold, margin)

    @staticmethod
    def _score(span: str, entry: Entry) -> float:
        norm = _normal(span)
        if not norm:
            return 0.0
        best = 0.0
        for form in entry.forms:
            candidate = _normal(form)
            if norm == candidate:
                # Aliases are explicit, deterministic opt-ins.
                return 1.0
            longest = max(len(norm), len(candidate))
            best = max(best, 1.0 - _distance(norm, candidate) / longest)
        return best

    def correct(self, text: str) -> str:
        if not text or not self.entries:
            return text
        matches = list(_WORD.finditer(text))
        replacements: list[tuple[int, int, str]] = []
        i = 0
        while i < len(matches):
            chosen: tuple[int, int, str] | None = None
            # Small spans cover word<->phrase correction without sentence rewriting.
            for width in range(min(4, len(matches) - i), 0, -1):
                start, end = matches[i].start(), matches[i + width - 1].end()
                span = text[start:end]
                scored = sorted(((self._score(span, e), e) for e in self.entries), key=lambda x: x[0], reverse=True)
                best, entry = scored[0]
                second = scored[1][0] if len(scored) > 1 else 0.0
                if best >= self.threshold and best - second >= self.margin:
                    chosen = (start, end, entry.canonical)
                    break
            if chosen:
                replacements.append(chosen)
                while i < len(matches) and matches[i].start() < chosen[1]:
                    i += 1
            else:
                i += 1
        for start, end, replacement in reversed(replacements):
            text = text[:start] + replacement + text[end:]
        return text
