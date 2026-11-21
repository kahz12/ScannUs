"""
core/providers/errors.py — the exception every provider raises when it cannot answer.
"""


class ProviderError(RuntimeError):
    """
    The provider could not produce a reply: a missing client, a request that
    failed after its retries, or a stream cut short. The message starts with
    the provider name. When the stream breaks partway, the text already
    yielded is incomplete and callers drop it.
    """
