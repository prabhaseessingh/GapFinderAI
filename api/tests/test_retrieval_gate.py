"""Vector gate (floor + margin) with scores measured live on the Qwen3 @384 embeddings (2026-11-18)."""

from uuid import uuid4

from app.services.retrieval import MIN_VECTOR_SIMILARITY, VECTOR_MARGIN, keep_vector_matches


def ids(scored: list[float]) -> list[tuple[object, float]]:
    return [(uuid4(), score) for score in scored]


def test_cross_language_answer_is_kept_although_below_old_fixed_cutoff() -> None:
    # Punjabi / Telugu questions vs English notes: right unit first at 0.326 / 0.330 (fixed 0.35 dropped it).
    assert [round(s, 3) for _, s in keep_vector_matches(ids([0.326, 0.309, 0.301]))] == [0.326]
    assert [round(s, 3) for _, s in keep_vector_matches(ids([0.330, 0.287, 0.239]))] == [0.33]


def test_in_domain_near_miss_is_dropped() -> None:
    # "What is Ohm's law?" against a maths-only workspace (live: 0.305 / 0.255; Hindi 0.296 / 0.281).
    assert keep_vector_matches(ids([0.305, 0.255])) == []
    assert keep_vector_matches(ids([0.296, 0.281])) == []


def test_same_language_keeps_only_matches_close_to_the_best() -> None:
    kept = keep_vector_matches(ids([0.685, 0.66, 0.53, 0.43]))
    assert [round(s, 3) for _, s in kept] == [0.685, 0.66]


def test_off_topic_question_gets_no_vector_evidence() -> None:
    assert keep_vector_matches(ids([0.137, 0.09, 0.069])) == []


def test_empty_and_constants() -> None:
    assert keep_vector_matches([]) == []
    assert MIN_VECTOR_SIMILARITY == 0.31 and VECTOR_MARGIN == 0.06
