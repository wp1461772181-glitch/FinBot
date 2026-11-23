"""Answer checks for ruler: fold text spellings, then test the required and forbidden phrases."""

import re
import unicodedata

from ruler.cases import Checks

# A comma or space between digits that is followed by exactly three digits is a thousands separator.
_THOUSANDS_SEPARATOR = re.compile(r"(?<=[0-9])[ ,](?=[0-9]{3}(?![0-9]))")
# "44 亿" and "44亿" are the same figure, so drop a space between a digit and CJK text.
_DIGIT_SPACE_CJK = re.compile(
    r"(?<=[0-9]) (?=[぀-ヿ㐀-䶿一-鿿가-힯])"
)
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Fold a string so that equivalent spellings of the same figure compare equal."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = _WHITESPACE.sub(" ", text).strip()
    previous = None
    while previous != text:
        previous = text
        text = _THOUSANDS_SEPARATOR.sub("", text)
    return _DIGIT_SPACE_CJK.sub("", text)


def run_checks(checks: Checks, *, answer: str, status: str) -> list[str]:
    """Return the names of the failed checks, in order; an empty list means the turn passed."""
    failed = []
    if status != checks.status:
        failed.append("status")
    haystack = normalize(answer)
    for index, alternatives in enumerate(checks.include_any):
        if not any(normalize(needle) in haystack for needle in alternatives):
            failed.append(f"include_any[{index}]")
    for index, needle in enumerate(checks.exclude):
        if normalize(needle) in haystack:
            failed.append(f"exclude[{index}]")
    return failed
