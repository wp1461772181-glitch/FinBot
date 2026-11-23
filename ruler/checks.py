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


def _contains(haystack: str, needle: str) -> bool:
    """Substring test that keeps a figure whole: a needle starting or ending with a digit must not match
    inside a longer number (13.4 in 113.4 or 13.45, 68 in 168 or 68.5); other needles match as plain text."""
    if not needle:
        return True
    start = haystack.find(needle)
    while start != -1:
        end = start + len(needle)
        before_ok = not (needle[0].isdigit() and start > 0 and (haystack[start - 1].isdigit() or haystack[start - 1] == "."))
        after = haystack[end:end + 2]
        after_ok = not (
            needle[-1].isdigit()
            and ((after[:1].isdigit()) or (after[:1] == "." and after[1:2].isdigit()))
        )
        if before_ok and after_ok:
            return True
        start = haystack.find(needle, start + 1)
    return False


def run_checks(checks: Checks, *, answer: str, status: str) -> list[str]:
    """Return the names of the failed checks, in order; an empty list means the turn passed."""
    failed = []
    if checks.status != "any" and status != checks.status:
        failed.append("status")
    haystack = normalize(answer)
    for index, alternatives in enumerate(checks.include_any):
        if not any(_contains(haystack, normalize(needle)) for needle in alternatives):
            failed.append(f"include_any[{index}]")
    for index, needle in enumerate(checks.exclude):
        if _contains(haystack, normalize(needle)):
            failed.append(f"exclude[{index}]")
    return failed
