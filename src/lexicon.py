"""Model-agnostic, surgical correction of canonical Skyrim entities."""

from __future__ import annotations

import json
import re
import time
import unicodedata
from bisect import bisect_right
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Mapping

_WORD = re.compile(r"[\w]+(?:['’][\w]+)*", re.UNICODE)
_LETTERS = re.compile(r"[^a-z]+")

# This is a risk feature, not a test for whether a span is meaningful. Real ASR
# errors are often ordinary words ("your Vaskar", "white run").
_COMMON_WORDS = frozenset(
    "a about after again all an and are around as at be before between but by can "
    "come did do down enter entered for from get go had has have he her here him his "
    "hold i in into is it its left long me my near no not of on or our out over right "
    "college room run she so some speak speaking take talk tell than that the their them then "
    "there they this through to toward towards travel traveled travelled traveling up "
    "us visit visited was way we were what when where white who why will with you your"
    .split()
)
_LOCATION_CUES = frozenset(
    "at enter entered from head headed in inside into investigate investigated leave left "
    "near reach reached return returned to toward towards travel traveled travelled "
    "traveling visit visited"
    .split()
)


def _normal(value: str) -> str:
    return " ".join(_WORD.findall(value.casefold()))


def _compact(value: str) -> str:
    return "".join(_WORD.findall(value.casefold()))


def _ascii_letters(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return _LETTERS.sub("", decomposed.encode("ascii", "ignore").decode("ascii"))


def _phonetic_keys(value: str) -> tuple[str, ...]:
    """Return compact pronunciation-oriented keys derived only from text.

    This is deliberately a lightweight phonetic hash, not character-distance
    matching. Digraphs and broad consonant families retain likely sound shape;
    vowels are retained only at the start. Initial Y gets both glide and vowel
    interpretations, which covers names such as Jorrvaskr and Uthgerd without
    storing observed ASR outputs.
    """
    letters = _ascii_letters(value)
    if not letters:
        return ()

    initial_variants = (letters,)
    if letters.startswith("y") and len(letters) > 1:
        initial_variants = ("j" + letters[1:], letters[1:])

    keys: list[str] = []
    for variant in initial_variants:
        units: list[str] = []
        i = 0
        while i < len(variant):
            pair = variant[i : i + 2]
            if pair in {"th", "dh"}:
                units.append("T")
                i += 2
                continue
            if pair in {"sh", "ch", "zh"}:
                units.append("S")
                i += 2
                continue
            if pair == "ph":
                units.append("F")
                i += 2
                continue
            if pair in {"ck", "qu"}:
                units.append("K")
                i += 2
                continue
            char = variant[i]
            if char in "aeiou":
                if not units:
                    units.append("A")
            elif char in "bpfv":
                units.append("F")
            elif char in "cgjkqx":
                units.append("K" if char not in "j" else "J")
            elif char in "dt":
                units.append("T")
            elif char in "sz":
                units.append("S")
            elif char == "y":
                units.append("J")
            elif char in "lmrn":
                units.append(char.upper())
            # H and W mostly alter adjacent vowels; the hash omits them.
            i += 1
        collapsed = "".join(unit for index, unit in enumerate(units) if not index or unit != units[index - 1])
        if collapsed and collapsed not in keys:
            keys.append(collapsed)
    return tuple(keys)


def _phonetic_sequences(value: str) -> tuple[tuple[str, ...], ...]:
    """Return richer approximate sound sequences for finalist scoring."""
    letters = _ascii_letters(value)
    if not letters:
        return ()
    initial_variants = (letters,)
    if letters.startswith("y") and len(letters) > 1:
        initial_variants = ("j" + letters[1:], letters[1:])
    sequences: list[tuple[str, ...]] = []
    for variant in initial_variants:
        units: list[str] = []
        i = 0
        while i < len(variant):
            pair = variant[i : i + 2]
            if pair in {"th", "dh"}:
                units.append("T")
                i += 2
                continue
            if pair in {"sh", "ch", "zh"}:
                units.append("S")
                i += 2
                continue
            if pair == "ph":
                units.append("F")
                i += 2
                continue
            if pair in {"ck", "qu"}:
                units.append("K")
                i += 2
                continue
            char = variant[i]
            if char in "aeiou":
                units.append(char.upper())
            elif char in "bpfv":
                units.append("F")
            elif char in "cgkqx":
                units.append("K")
            elif char == "j":
                units.append("J")
            elif char in "dt":
                units.append("T")
            elif char in "sz":
                units.append("S")
            elif char == "y":
                units.append("J")
            elif char in "lmrn":
                units.append(char.upper())
            i += 1
        collapsed = tuple(
            unit for index, unit in enumerate(units) if not index or unit != units[index - 1]
        )
        if collapsed and collapsed not in sequences:
            sequences.append(collapsed)
    return tuple(sequences)


def _sequence_similarity(
    left_sequences: tuple[tuple[str, ...], ...],
    right_sequences: tuple[tuple[str, ...], ...],
) -> float:
    """Weighted distance over derived sound units, never over characters."""
    vowels = frozenset("AEIOU")

    def distance(a: tuple[str, ...], b: tuple[str, ...]) -> float:
        previous = [float(index) for index in range(len(b) + 1)]
        for i, left_unit in enumerate(a, 1):
            current = [float(i)]
            for j, right_unit in enumerate(b, 1):
                if left_unit == right_unit:
                    substitution = 0.0
                elif left_unit in vowels and right_unit in vowels:
                    substitution = 0.25
                else:
                    substitution = 1.0
                current.append(
                    min(current[-1] + 1.0, previous[j] + 1.0, previous[j - 1] + substitution)
                )
            previous = current
        return previous[-1]

    best = 0.0
    for left_sequence in left_sequences:
        for right_sequence in right_sequences:
            longest = max(len(left_sequence), len(right_sequence))
            best = max(best, 1.0 - distance(left_sequence, right_sequence) / longest)
    return best


def _phonetic_similarity_from_parts(
    left_keys: tuple[str, ...],
    left_sequences: tuple[tuple[str, ...], ...],
    right_keys: tuple[str, ...],
    right_sequences: tuple[tuple[str, ...], ...],
) -> float:
    """Compare derived sound shapes without storing transcription aliases.

    The detailed sequence score handles vowel variation. The coarse-key score
    recovers consonant insertions, deletions, and reordered sounds commonly
    emitted by compact ASR models (for example, Skolafen/Skuldafn).
    """
    key_score = max(
        (
            SequenceMatcher(None, left, right, autojunk=False).ratio()
            for left in left_keys
            for right in right_keys
        ),
        default=0.0,
    )
    return max(key_score, _sequence_similarity(left_sequences, right_sequences))


def _orthographic_similarity(left: str, right: str) -> float:
    """Use spelling only to rank phonetic finalists, never to retrieve them."""
    return SequenceMatcher(
        None, _ascii_letters(left), _ascii_letters(right), autojunk=False
    ).ratio()


@dataclass(frozen=True)
class Entry:
    canonical: str
    category: str | None = None


@dataclass(frozen=True)
class CompiledEntry:
    entry: Entry
    normalized: str
    compact: str
    token_count: int
    phonetic_keys: tuple[str, ...]
    phonetic_sequences: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class CandidateScore:
    canonical: str
    method: str
    source_score: float
    context_score: float
    risk_penalty: float
    total: float


@dataclass(frozen=True)
class SpanDecision:
    start: int
    end: int
    source: str
    candidates: tuple[CandidateScore, ...]
    accepted: bool
    reason: str


@dataclass(frozen=True)
class CorrectionTrace:
    output: str
    decisions: tuple[SpanDecision, ...]
    stage_timings_ms: Mapping[str, float]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _Proposal:
    start: int
    end: int
    replacement: str
    value: float


class SkyrimLexicon:
    """Load-once canonical compiler and text-in/text-out correction engine."""

    _MIN_RETRIEVAL = 0.60
    _MIN_SOURCE = 0.68
    _MIN_TOTAL = 0.82
    _MIN_RUNNER_MARGIN = 0.01
    _UNCHANGED_SCORE = 0.72
    _MIN_UNCHANGED_GAIN = 0.10
    _MAX_FINALISTS = 8

    def __init__(self, entries: Iterable[Entry] = ()):
        self.entries = tuple(entries)
        compiled: list[CompiledEntry] = []
        canonical_exact: dict[str, list[int]] = {}
        compact_exact: dict[str, list[int]] = {}
        max_tokens = 1
        for index, entry in enumerate(self.entries):
            normalized = _normal(entry.canonical)
            compact = _compact(entry.canonical)
            keys = _phonetic_keys(entry.canonical)
            token_count = len(normalized.split())
            max_tokens = max(max_tokens, token_count)
            sequences = _phonetic_sequences(entry.canonical)
            compiled.append(CompiledEntry(entry, normalized, compact, token_count, keys, sequences))
            canonical_exact.setdefault(normalized, []).append(index)
            compact_exact.setdefault(compact, []).append(index)
        self._compiled = tuple(compiled)
        self._canonical_exact = {key: tuple(value) for key, value in canonical_exact.items()}
        self._compact_exact = {key: tuple(value) for key, value in compact_exact.items()}
        # One canonical token may be split into several ASR words. The bound is
        # derived from the lexicon rather than a fixed one-to-four-token scan.
        self._max_span_tokens = min(10, max_tokens + 2)

    @classmethod
    def load(cls, path: str | Path) -> "SkyrimLexicon":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid Skyrim lexicon {path}: {exc}") from exc
        if isinstance(raw, dict):
            raw = raw.get("entries", [])
        if not isinstance(raw, list):
            raise ValueError("Skyrim lexicon must be an array or an object with an entries array")
        entries: list[Entry] = []
        seen: dict[str, str] = {}
        for item in raw:
            if isinstance(item, str):
                item = {"canonical": item}
            if not isinstance(item, dict) or not isinstance(item.get("canonical"), str):
                raise ValueError("Each Skyrim lexicon entry requires a string canonical field")
            canonical = item["canonical"].strip()
            key = _normal(canonical)
            if not canonical or not key:
                continue
            if key in seen:
                raise ValueError(
                    f"Canonical collision: {canonical!r} and {seen[key]!r} normalize identically"
                )
            category = item.get("category")
            if category is not None and not isinstance(category, str):
                raise ValueError(f"Category for {canonical!r} must be a string")
            seen[key] = canonical
            entries.append(Entry(canonical, category))
        return cls(entries)

    @staticmethod
    def _context_score(
        words: list[str], first: int, last: int, category: str | None
    ) -> float:
        if category not in {None, "location"} or first == 0:
            return 0.0
        immediate = words[first - 1]
        cued = immediate in _LOCATION_CUES
        if not cued and immediate in {"of", "the"} and first >= 2:
            cued = words[first - 2] in _LOCATION_CUES
        if cued:
            return 0.08
        return 0.0

    @staticmethod
    def _risk_penalty(source_words: list[str], method: str) -> float:
        # Exact split/join forms are explicit enough to win without
        # ordinary-word risk. In a Skyrim-focused service, "White Run" is
        # overwhelmingly more likely to mean "Whiterun".
        if method == "compact":
            return 0.0
        penalty = 0.0
        if source_words and all(word in _COMMON_WORDS for word in source_words):
            penalty += 0.22
        if sum(map(len, source_words)) <= 4:
            penalty += 0.12
        return penalty

    def _candidate_methods(
        self, source: str, *, allow_phonetic: bool = True
    ) -> dict[int, str]:
        normalized = _normal(source)
        compact = _compact(source)
        methods: dict[int, str] = {}
        priority = {"phonetic": 1, "compact": 2, "canonical": 3}

        def add(indices: Iterable[int], method: str) -> None:
            for index in indices:
                current_priority = priority[methods[index]] if index in methods else 0
                if priority[method] > current_priority:
                    methods[index] = method

        add(self._canonical_exact.get(normalized, ()), "canonical")
        if methods:
            return methods
        add(self._compact_exact.get(compact, ()), "compact")
        if methods:
            return methods
        if allow_phonetic and self._phonetic_source_allowed(source):
            add(self._phonetic_candidates(source), "phonetic")
        return methods

    @staticmethod
    def _phonetic_source_allowed(source: str) -> bool:
        """Limit fuzzy work to ASR spans that look like proper names.

        Canonical and compact exact matches remain case-insensitive. Approximate
        correction uses the capitalization emitted for proper nouns by the
        supported models, which prevents ordinary sentence text from being
        consumed by a merely similar Skyrim name.
        """
        tokens = _WORD.findall(source)
        if not tokens:
            return False
        if len(tokens) == 1:
            return tokens[0][0].isupper() and len(_ascii_letters(tokens[0])) >= 4
        final = tokens[-1]
        return (
            final[0].isupper()
            and len(_ascii_letters(final)) >= 4
            and final.casefold() not in _COMMON_WORDS
        )

    def _phonetic_candidates(self, source: str) -> tuple[int, ...]:
        source_keys = _phonetic_keys(source)
        source_sequences = _phonetic_sequences(source)
        source_token_count = len(_normal(source).split())
        source_length = len(_ascii_letters(source))
        ranked: list[tuple[float, int]] = []
        for index, compiled in enumerate(self._compiled):
            if abs(source_token_count - compiled.token_count) > 1:
                continue
            canonical_length = len(_ascii_letters(compiled.entry.canonical))
            if min(source_length, canonical_length) / max(source_length, canonical_length) < 0.55:
                continue
            similarity = _phonetic_similarity_from_parts(
                source_keys,
                source_sequences,
                compiled.phonetic_keys,
                compiled.phonetic_sequences,
            )
            if similarity >= self._MIN_RETRIEVAL:
                ranked.append((similarity, index))
        ranked.sort(
            key=lambda item: (
                -item[0],
                self._compiled[item[1]].entry.canonical.casefold(),
            )
        )
        return tuple(index for _, index in ranked[: self._MAX_FINALISTS])

    def _score_span(
        self,
        text: str,
        words: list[str],
        first: int,
        last: int,
        start: int,
        end: int,
    ) -> tuple[_Proposal | None, SpanDecision | None]:
        source = text[start:end]
        source_words = _normal(source).split()
        source_compact = _compact(source)
        contains_exact_subspan = any(
            " ".join(source_words[sub_first:sub_last]) in self._canonical_exact
            for sub_first in range(len(source_words))
            for sub_last in range(sub_first + 1, len(source_words) + 1)
            if sub_first != 0 or sub_last != len(source_words)
        )
        methods = self._candidate_methods(
            source, allow_phonetic=not contains_exact_subspan
        )
        if not methods:
            return None, None
        base_scores = {"canonical": 1.00, "compact": 0.98}
        source_keys = _phonetic_keys(source)
        source_sequences = _phonetic_sequences(source)
        scored: list[tuple[int, CandidateScore]] = []
        for index, method in methods.items():
            compiled = self._compiled[index]
            spelling_compatibility = _orthographic_similarity(
                source, compiled.entry.canonical
            )
            phonetic_compatibility = _phonetic_similarity_from_parts(
                source_keys,
                source_sequences,
                compiled.phonetic_keys,
                compiled.phonetic_sequences,
            )
            if method == "phonetic":
                if contains_exact_subspan:
                    continue
                token_difference = len(source_words) - compiled.token_count
                if abs(token_difference) > 1:
                    continue
                # Do not swallow an adjacent word when the canonical itself is
                # already an exact prefix/suffix of this wider source span.
                if token_difference > 0 and (
                    source_compact.startswith(compiled.compact)
                    or source_compact.endswith(compiled.compact)
                ):
                    continue
                if token_difference and spelling_compatibility < 0.70:
                    continue
                if (
                    len(source_words) > 1
                    and source_words[0] in _COMMON_WORDS
                    and phonetic_compatibility < 0.90
                ):
                    continue
            compatibility = (
                0.80 * phonetic_compatibility
                + 0.20 * spelling_compatibility
                - 0.05 * abs(len(source_words) - compiled.token_count)
                if method == "phonetic"
                else base_scores[method]
            )
            source_score = compatibility
            risk = self._risk_penalty(source_words, method)
            context = self._context_score(
                words, first, last, compiled.entry.category
            )
            confidence = 0.50 + 0.50 * compatibility if method == "phonetic" else compatibility
            total = confidence + context - risk
            scored.append(
                (
                    index,
                    CandidateScore(
                        canonical=self._compiled[index].entry.canonical,
                        method=method,
                        source_score=source_score,
                        context_score=context,
                        risk_penalty=risk,
                        total=total,
                    ),
                )
            )
        if not scored:
            return None, None
        scored.sort(key=lambda item: (-item[1].total, item[1].canonical.casefold()))
        best_index, best = scored[0]
        runner_total = scored[1][1].total if len(scored) > 1 else 0.0
        exact_key_collision = False
        if len(scored) > 1 and best.method == scored[1][1].method == "phonetic":
            source_key_set = set(source_keys)
            exact_key_collision = bool(
                source_key_set.intersection(self._compiled[best_index].phonetic_keys)
                and source_key_set.intersection(
                    self._compiled[scored[1][0]].phonetic_keys
                )
            )
        reason = "accepted"
        if best.source_score < self._MIN_SOURCE:
            reason = "weak-source"
        elif best.total < self._MIN_TOTAL:
            reason = "low-confidence"
        elif exact_key_collision:
            reason = "ambiguous-runner-up"
        elif best.total - runner_total < self._MIN_RUNNER_MARGIN:
            reason = "ambiguous-runner-up"
        elif best.total - self._UNCHANGED_SCORE < self._MIN_UNCHANGED_GAIN:
            reason = "unchanged-margin"
        candidates = tuple(item[1] for item in scored)
        accepted = reason == "accepted"
        decision = SpanDecision(start, end, source, candidates, accepted, reason)
        if not accepted:
            return None, decision
        return (
            _Proposal(
                start,
                end,
                self._compiled[best_index].entry.canonical,
                (best.total - self._UNCHANGED_SCORE)
                * self._compiled[best_index].token_count
                + (end - start) * 1e-6,
            ),
            decision,
        )

    @staticmethod
    def _select_non_overlapping(proposals: list[_Proposal]) -> list[_Proposal]:
        if not proposals:
            return []
        ordered = sorted(proposals, key=lambda proposal: (proposal.end, proposal.start))
        ends = [proposal.end for proposal in ordered]
        previous = [bisect_right(ends, proposal.start) - 1 for proposal in ordered]
        values = [0.0] * (len(ordered) + 1)
        chosen: list[tuple[int, ...]] = [()] * (len(ordered) + 1)
        for position, proposal in enumerate(ordered, 1):
            include_from = previous[position - 1] + 1
            include_value = values[include_from] + proposal.value
            include_set = chosen[include_from] + (position - 1,)
            exclude_value = values[position - 1]
            if include_value > exclude_value + 1e-12:
                values[position], chosen[position] = include_value, include_set
            else:
                values[position], chosen[position] = exclude_value, chosen[position - 1]
        return [ordered[index] for index in chosen[-1]]

    def _correct(self, text: str, *, diagnostics: bool) -> tuple[str, CorrectionTrace | None]:
        if not text or not self.entries:
            trace = CorrectionTrace(text, (), {"total": 0.0}) if diagnostics else None
            return text, trace
        total_started = time.perf_counter_ns()
        tokenize_started = total_started
        matches = list(_WORD.finditer(text))
        words = [match.group().casefold() for match in matches]
        tokenize_done = time.perf_counter_ns()
        proposals: list[_Proposal] = []
        decisions: list[SpanDecision] = []
        score_started = tokenize_done
        for first in range(len(matches)):
            for width in range(1, min(self._max_span_tokens, len(matches) - first) + 1):
                last = first + width - 1
                start, end = matches[first].start(), matches[last].end()
                proposal, decision = self._score_span(text, words, first, last, start, end)
                if proposal is not None:
                    proposals.append(proposal)
                if diagnostics and decision is not None:
                    decisions.append(decision)
        score_done = time.perf_counter_ns()
        selected = self._select_non_overlapping(proposals)
        select_done = time.perf_counter_ns()
        output = text
        for proposal in sorted(selected, key=lambda item: item.start, reverse=True):
            output = output[: proposal.start] + proposal.replacement + output[proposal.end :]
        reconstruct_done = time.perf_counter_ns()
        if not diagnostics:
            return output, None
        selected_spans = {(proposal.start, proposal.end, proposal.replacement) for proposal in selected}
        final_decisions = tuple(
            SpanDecision(
                decision.start,
                decision.end,
                decision.source,
                decision.candidates,
                decision.accepted
                and bool(decision.candidates)
                and (decision.start, decision.end, decision.candidates[0].canonical) in selected_spans,
                decision.reason
                if not decision.accepted
                or (decision.start, decision.end, decision.candidates[0].canonical) in selected_spans
                else "overlap-not-selected",
            )
            for decision in decisions
        )
        timings = {
            "tokenize": (tokenize_done - tokenize_started) / 1e6,
            "retrieve_score_context": (score_done - score_started) / 1e6,
            "select": (select_done - score_done) / 1e6,
            "reconstruct": (reconstruct_done - select_done) / 1e6,
            "total": (reconstruct_done - total_started) / 1e6,
        }
        return output, CorrectionTrace(output, final_decisions, timings)

    def correct(self, text: str) -> str:
        return self._correct(text, diagnostics=False)[0]

    def correct_with_trace(self, text: str) -> tuple[str, CorrectionTrace]:
        output, trace = self._correct(text, diagnostics=True)
        assert trace is not None
        return output, trace
