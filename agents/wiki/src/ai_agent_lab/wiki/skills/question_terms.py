"""Turning a question into search terms, deterministically.

A question is not a query. "What is in scope for VAT this year?" contains three
words that carry meaning and six that appear on every page of every wiki, and a
search engine matching all of them finds nothing.

The obvious fix - ask a model to rewrite the question - is the wrong one here.
It adds a step whose failures are silent, it costs a call before the real work
starts, and it makes the same question retrieve different pages on different
runs, which would quietly ruin the framework comparison.

So the reduction is done in code. It is crude, and deliberately so: dropping
function words and punctuation is a transformation with one right answer, and
anything cleverer would be guessing about a language it cannot see.
"""

from __future__ import annotations

import re

DEFAULT_MAX_TERMS = 8
DEFAULT_ATTEMPTS = 3
MIN_TERM_LENGTH = 2

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# English and French function words. The agent is used against wikis written in
# both, and a stop list that only knew English would leave "quel", "pour" and
# "dans" in every French query.
_STOP_WORDS = frozenset(
    {
        # English
        "a", "about", "all", "am", "an", "and", "any", "are", "as", "at", "be",
        "been", "but", "by", "can", "did", "do", "does", "for", "from", "get",
        "give", "had", "has", "have", "how", "i", "if", "in", "into", "is", "it",
        "its", "me", "much", "must", "my", "of", "on", "or", "our", "please",
        "should", "so", "some", "tell", "than", "that", "the", "their", "them",
        "then", "there", "these", "they", "this", "those", "to", "us", "was",
        "we", "were", "what", "when", "where", "which", "who", "why", "will",
        "with", "would", "you", "your",
        # French
        "au", "aux", "avec", "ce", "ces", "comment", "dans", "de", "des", "du",
        "elle", "en", "est", "et", "il", "ils", "je", "la", "le", "les", "leur",
        "lui", "ma", "mais", "mes", "moi", "mon", "ne", "nos", "notre",
        "nous", "ou", "par", "pas", "peut", "pour", "pourquoi", "quand",
        "que", "quel", "quelle", "quelles", "quels", "qui", "quoi", "sa", "se",
        "ses", "son", "sont", "sur", "ta", "te", "tes", "toi", "ton", "tu",
        "un", "une", "vos", "votre", "vous", "y",
    }
)


class QuestionTerms:
    """Reduces a question to the words worth searching for."""

    def __init__(self, *, max_terms: int = DEFAULT_MAX_TERMS) -> None:
        self._max_terms = max_terms

    def of(self, question: str) -> str:
        """Return the search text a question should become.

        A question made entirely of function words - "what is this?" - reduces to
        nothing. The original is returned in that case rather than an empty
        query: the caller's own emptiness check should be what refuses it, and
        turning a bad question into a search for the whole wiki would be worse
        than passing it through.
        """
        terms = self._terms(question)
        return " ".join(terms) if terms else question.strip()

    def ladder(self, question: str, *, attempts: int = DEFAULT_ATTEMPTS) -> tuple[str, ...]:
        """Return progressively broader queries for one question.

        Search engines differ in a way that matters here. Confluence ranks by
        relevance and answers a multi-term query with its best matches; a server
        matching terms literally requires *all* of them, and one incidental word
        - "year", "current", a project name spelled differently - is enough to
        return nothing at all. The agent would then report that the
        documentation is silent, which is the one thing it must never say
        wrongly.

        So the query is broadened rather than assumed to work: the full set of
        content words first, then shorter prefixes of it. A ranking engine
        settles this on the first attempt and never sees the rest. Trailing terms
        are the ones dropped because a question states its subject before its
        qualifiers, in English and in French alike.

        The ladder is bounded and deterministic, which matters as much as its
        being useful: the same question must retrieve the same pages on every
        run, or the framework comparison measures noise.
        """
        terms = self._terms(question)
        if not terms:
            return (question.strip(),)

        queries: list[str] = []
        for length in range(len(terms), 0, -1):
            queries.append(" ".join(terms[:length]))
            if len(queries) == attempts:
                break
        return tuple(queries)

    def _terms(self, question: str) -> list[str]:
        """Extract the meaningful words, in order, without repeats."""
        found: dict[str, None] = {}
        for match in _WORD.finditer(question):
            word = match.group().casefold()
            if len(word) < MIN_TERM_LENGTH or word in _STOP_WORDS:
                continue
            found.setdefault(word, None)
            if len(found) == self._max_terms:
                break
        return list(found)
