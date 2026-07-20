class RecallError(Exception):
    """Base for every recall failure. Every one of these is deliberate and reported."""


class ConfigError(RecallError):
    """Malformed or missing configuration."""


class UnknownTagError(RecallError):
    """Source tag not in the registry. Always lists the known tags."""

    def __init__(self, tag: str, known: list[str]) -> None:
        known_str = ", ".join(sorted(known)) if known else "(none registered)"
        super().__init__(
            f"Unknown source tag {tag!r}. Known tags: {known_str}. "
            f"Register the source with: recall register <path>"
        )
        self.tag = tag
        self.known = known


class EmbedderUnreachableError(RecallError):
    """The embedding backend could not be reached. Names the endpoint and the fix.

    We never fall back to a different model. A silently-substituted embedder
    produces vectors that are meaningless against the stored ones.
    """


class DimensionMismatchError(RecallError):
    """Configured model's dimension or name differs from what the database was built with.

    A vector column has one fixed width, so the model is fixed for the life of
    the database. We refuse to index rather than write a corrupt index.
    """

    def __init__(
        self, stored_model: str, stored_dim: int, configured_model: str, configured_dim: int
    ) -> None:
        super().__init__(
            f"This database was indexed with {stored_model!r} ({stored_dim} dimensions) "
            f"but the configured embedder is {configured_model!r} ({configured_dim} dimensions). "
            f"The embedding model is fixed for the life of the database. "
            f"To change model, run: recall reindex"
        )


class StoreNotInitialisedError(RecallError):
    """The database has no recall schema yet. Run: recall init"""


class InvalidLimitError(RecallError):
    """`limit` failed validation at the MCP or store boundary.

    limit=0 used to silently return zero results — indistinguishable from "no
    matches" to a caller. A negative limit reached raw SQL and raised an
    opaque psycopg error instead of a recall error. Both are exactly the kind
    of silent/opaque failure this product exists to prevent, so we validate
    at the boundary and name the bad value and the fix.
    """

    def __init__(self, limit: int, maximum: int) -> None:
        if limit > maximum:
            reason = f"exceeds the maximum of {maximum}"
        else:
            reason = "must be a positive integer"
        super().__init__(
            f"Invalid limit {limit!r}: {reason}. Pass a limit between 1 and {maximum}."
        )
        self.limit = limit
        self.maximum = maximum
