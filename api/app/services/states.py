from collections.abc import Mapping

# uploaded → scanning (verify object) → extracting → chunking → embedding → mapping → ready
DOCUMENT_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "uploaded": frozenset({"scanning", "failed"}),
    "scanning": frozenset({"extracting", "failed"}),
    "extracting": frozenset({"chunking", "failed"}),
    "chunking": frozenset({"embedding", "failed"}),
    "embedding": frozenset({"mapping", "ready", "failed"}),
    "mapping": frozenset({"ready", "failed"}),
    "ready": frozenset(),
    # A failed document re-enters the pipeline only through an explicit student retry.
    "failed": frozenset({"scanning"}),
}
PROCESSING_STATES = frozenset({"scanning", "extracting", "chunking", "embedding", "mapping"})


def require_document_transition(current: str, target: str) -> None:
    if target not in DOCUMENT_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"Invalid document state transition: {current} → {target}")
