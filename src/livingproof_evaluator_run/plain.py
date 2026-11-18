"""Plain text for the result descriptor.

The contract's ``descriptor`` plain-text pattern (livingproof-evaluator
``schema/descriptor.schema.json``, ``$defs/plain``) refuses ``<``, ``>``, C0 and C1 control
characters (including DEL) and the line and paragraph separators, and needs at least one
visible character. Every descriptor string must match it, and so must the text of a finding.

Values copied out of evidence (a recorded digest, a name) are not trusted to follow it. They
are *shown escaped*, not dropped and not rejected: a recorded value with an odd character is
still a pin that differs from the lock, so it stays a finding, and the reader can see exactly
what was recorded. ``a<b>\\n`` is shown as ``a\\u003cb\\u003e\\x0a``. The same escape applies to
anything else that reaches the descriptor, so the result validates whatever the evidence says.

This module repeats the contract's pattern and lengths because the evaluator has no runtime dependency on
the contract kit. ``evaluate`` checks its own descriptor against them before writing, so a
result that would not validate is never written and the command exits non-zero instead.
"""

from __future__ import annotations

import re

# Characters the descriptor plain-text pattern refuses.
_REFUSED = re.compile("[<>\u0000-\u001f\u007f-\u009f\u2028\u2029]")
# Characters that do not count as visible (the pattern's lookahead).
_INVISIBLE = re.compile(
    "[\\s\u00ad\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891\u08e2\u180e\u200b-\u200f"
    "\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb"
    "\U000110bd\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3\U0001d173-\U0001d17a"
    "\U000e0001\U000e0020-\U000e007f]"
)
# A bound for a value copied out of evidence. A sha256 with its prefix is 71 characters.
VALUE_LIMIT = 100

# Maximum lengths in the contract's ``descriptor.schema.json`` (kit v1.0.8). The descriptor
# and each finding in it are checked against these before a result is written.
DESCRIPTOR_LIMITS = {
    "title": 80,
    "short_title": 40,
    "icon_accessible_name": 120,
    "purpose": 400,
    "version": 64,
    "kind": 40,
    "source": 120,
    "success_copy": 400,
    "details_copy": 1000,
}
FINDING_LIMITS = {"text": 280, "severity": 40, "time": 40, "trial": 40, "reported_by": 80}
MAX_FINDINGS = 50


def is_plain(text: object) -> bool:
    """True when ``text`` matches the contract's descriptor plain-text pattern."""
    return (
        isinstance(text, str) and _REFUSED.search(text) is None and _INVISIBLE.sub("", text) != ""
    )


def escape(text: str) -> str:
    """``text`` with every refused character written as ``\\xNN`` or ``\\uNNNN``."""

    def one(match: re.Match[str]) -> str:
        code = ord(match.group())
        # < and > are written as \u003c and \u003e, so no markup survives in any form.
        return f"\\x{code:02x}" if code < 0x80 and match.group() not in "<>" else f"\\u{code:04x}"

    return _REFUSED.sub(one, text)


def shown(value: str) -> str:
    """A value copied out of evidence, bounded and then escaped, safe in descriptor text."""
    text = value if len(value) <= VALUE_LIMIT else value[: VALUE_LIMIT - 1] + "\u2026"
    return escape(text)


def plain(text: str) -> str:
    """Descriptor text from a string that may carry evidence: escaped, never refused."""
    return escape(text)
