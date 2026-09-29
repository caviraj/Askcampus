"""Token counting.

ARCHITECTURE.md section 8 sizes chunks in tokens but never says how a token is
counted, and AGENTS.md section 7 wants chunk sizes to come from config.py.
Rather than add tiktoken -- a compiled dependency, and a tokenizer Gemini does not
use anyway -- or call the API's countTokens endpoint once per chunk over the
network, this approximates from the text.

The approximation deliberately over-estimates. Against a 300-500 token target,
over-estimating produces slightly smaller chunks, which is harmless; under-
estimating overflows the model's context, which is not.
"""

from __future__ import annotations

import math
import re

# Three alternatives, tried in order: a word (letters, optionally joined by
# apostrophes or hyphens), a run of digits, or a single other character.
_TOKEN_PATTERN = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*|\d+|[^\s]")

# Rough characters per token for English prose in the subword vocabularies used by
# current models. Digits split far more aggressively than letters.
_CHARS_PER_WORD_TOKEN = 4
_CHARS_PER_DIGIT_TOKEN = 3


def count_tokens(text: str) -> int:
    """Approximate the number of tokens in `text`.

    Empty input is exactly 0, and the result depends on nothing but the input, so
    chunking stays reproducible.
    """
    if not text:
        return 0

    total = 0
    for match in _TOKEN_PATTERN.finditer(text):
        token = match.group()
        if token.isdigit():
            total += math.ceil(len(token) / _CHARS_PER_DIGIT_TOKEN)
        elif any(char.isalnum() for char in token):
            total += math.ceil(len(token) / _CHARS_PER_WORD_TOKEN)
        else:
            # Punctuation is never free, even when a real tokenizer would merge a
            # run of it into one token. One each is the safe direction.
            total += 1
    return total
