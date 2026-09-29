"""Provider errors.

Kept out of the vendor module so services can catch a provider failure without
importing a vendor SDK. `app/providers/gemini.py` raises it; the retry logic in
`app/services/embedding.py` reads `transient` to decide whether another attempt
could plausibly succeed.
"""

from __future__ import annotations


class ProviderError(Exception):
    """A failure talking to the model provider.

    `transient` distinguishes "try again" from "this will fail identically every
    time". A timeout or a 429 is transient; a 404 for a retired model is not, and
    retrying it three times with backoff only turns a fast failure into a slow
    one.
    """

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient
