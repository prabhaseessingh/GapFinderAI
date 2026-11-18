from typing import Any
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.providers.groq import AiCallContext, GroqOutputRejected, GroqProvider, strict_schema
from app.schemas.topics import CitationReference, ProposedTopic, TopicProposal
from app.services.importance_policy import MappedQuestion, compute_importance
from app.services.retrieval import apply_diversity, quote_in_source
from app.services.topics import merge_proposals
from app.services.translation import needs_translation


def test_importance_neutral_without_past_papers_and_scaled_with_them() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    assert {
        d.importance for d in compute_importance([a, b], [], workspace_question_count=0).values()
    } == {3}
    decisions = compute_importance(
        [a, b, c],
        [MappedQuestion(a, 10, 2022), MappedQuestion(a, 10, 2023), MappedQuestion(b, None, None)],
        workspace_question_count=3,
        student_overrides={c: 2},
    )
    assert decisions[a].importance == 5 and decisions[a].basis["years"] == [2022, 2023]
    assert decisions[b].importance == 1 + round(4 * 1 / 20)
    assert (decisions[c].importance, decisions[c].source) == (2, "student")


def test_quote_matching_normalises_whitespace_and_case_only() -> None:
    assert quote_in_source("cell  BIOLOGY", "Intro to Cell\nbiology.")
    assert not quote_in_source("cell biology basics", "Intro to Cell biology.")
    assert not quote_in_source("   ", "anything")


def test_diversity_caps_one_document() -> None:
    d1, d2 = uuid4(), uuid4()
    ordered = [(uuid4(), d1) for _ in range(6)] + [(uuid4(), d2) for _ in range(2)]
    chosen = apply_diversity(ordered, 4)
    assert sum(1 for cid, doc in ordered if cid in chosen and doc == d2) == 2


def test_merge_proposals_combines_duplicate_titles() -> None:
    chunk = uuid4()
    first = TopicProposal(
        topics=[
            ProposedTopic(
                title="Cells",
                parent_title=None,
                citations=[CitationReference(chunk_id=chunk, quote="a")],
            )
        ]
    )
    second = TopicProposal(
        topics=[
            ProposedTopic(
                title="cells",
                parent_title=None,
                citations=[CitationReference(chunk_id=chunk, quote="b")],
            ),
            ProposedTopic(
                title="Mitosis",
                parent_title="Orphan",
                citations=[CitationReference(chunk_id=chunk, quote="c")],
            ),
        ]
    )
    merged = merge_proposals([first, second])
    assert [t.title for t in merged.topics] == ["Cells", "Mitosis"]
    assert len(merged.topics[0].citations) == 2
    assert merged.topics[1].parent_title is None


def test_strict_schema_requires_all_fields_and_drops_unsupported_keywords() -> None:
    schema = strict_schema(TopicProposal)
    citation = schema["$defs"]["CitationReference"]
    assert citation["additionalProperties"] is False
    assert set(citation["required"]) == {"chunk_id", "quote"}
    assert "maxLength" not in citation["properties"]["quote"]
    topic = schema["$defs"]["ProposedTopic"]
    assert (
        {"title", "parent_title", "citations"} == set(topic["properties"]) == set(topic["required"])
    )


class _ScriptedGroq(GroqProvider):
    def __init__(self, replies: list[str]) -> None:
        settings = Settings(groq_api_key="k", groq_model="fast", groq_model_quality="quality")
        self.calls: list[tuple[str, str, int, dict[str, Any]]] = []
        super().__init__(
            settings,
            recorder=lambda ctx, model, outcome, code, ms, usage: self.calls.append(
                (outcome, str(code), ms, usage)
            ),
        )
        self.replies = replies
        self.models: list[str] = []

    def _complete(self, model: str, *_: Any) -> tuple[str, dict[str, Any]]:
        self.models.append(model)
        return self.replies.pop(0), {"total_tokens": 1}


def _valid_proposal(chunk: Any) -> str:
    return TopicProposal(
        topics=[
            ProposedTopic(
                title="Cells",
                parent_title=None,
                citations=[CitationReference(chunk_id=chunk, quote="cells")],
            )
        ]
    ).model_dump_json()


def test_invalid_output_is_rejected_then_retried_and_audited() -> None:
    chunk = uuid4()
    provider = _ScriptedGroq(["not json", _valid_proposal(chunk)])
    result = provider.structured(
        AiCallContext("op", "v1", None, None),
        output=TopicProposal,
        system="s",
        user="u",
        tier="quality",
    )
    assert result.topics[0].title == "Cells"
    assert [c[0] for c in provider.calls] == ["rejected", "accepted"]
    assert provider.models == ["quality", "quality"]


def test_domain_validator_failure_never_publishes() -> None:
    chunk = uuid4()
    provider = _ScriptedGroq([_valid_proposal(chunk), _valid_proposal(chunk)])

    def reject(_: TopicProposal) -> None:
        raise ValueError("INVALID_TOPIC_CITATION")

    with pytest.raises(GroqOutputRejected) as error:
        provider.structured(
            AiCallContext("op", "v1", None, None),
            output=TopicProposal,
            system="s",
            user="u",
            validate=reject,
        )
    assert error.value.code == "INVALID_TOPIC_CITATION"
    assert provider.models == ["fast", "fast"]
    assert all(call[0] == "rejected" for call in provider.calls)


def test_retry_tells_the_model_why_its_quote_was_rejected() -> None:
    """Calls run at temperature 0: a bare retry repeats the same elided quote (seen live)."""
    chunk = uuid4()
    prompts: list[str] = []

    class Capturing(_ScriptedGroq):
        def _complete(
            self, model: str, system: str, user: str, *_: Any
        ) -> tuple[str, dict[str, Any]]:
            prompts.append(user)
            return super()._complete(model)

    provider = Capturing([_valid_proposal(chunk), _valid_proposal(chunk)])
    seen = 0

    def reject_first(_: TopicProposal) -> None:
        nonlocal seen
        seen += 1
        if seen == 1:
            raise ValueError("CITATION_QUOTE_NOT_IN_SOURCE")

    provider.structured(
        AiCallContext("op", "v1", None, None),
        output=TopicProposal,
        system="s",
        user="u",
        validate=reject_first,
    )
    assert prompts[0] == "u"
    assert (
        prompts[1].startswith("u")
        and "CITATION_QUOTE_NOT_IN_SOURCE" in prompts[1]
        and "'...'" in prompts[1]
    )
    assert [c[0] for c in provider.calls] == ["rejected", "accepted"]


def test_source_rule_forbids_elided_quotes() -> None:
    from app.providers.groq import UNTRUSTED_SOURCE_RULE

    assert "'...'" in UNTRUSTED_SOURCE_RULE and "continuous passage" in UNTRUSTED_SOURCE_RULE


def test_translation_only_when_languages_differ() -> None:
    assert needs_translation("en", "hi-IN")
    assert not needs_translation("hi", "hi-IN")
    assert not needs_translation("und", "te-IN")
    assert needs_translation("en", "deccani-Latn")


def test_coverage_ignores_title_chunks_and_tolerates_one_uncited() -> None:
    from app.services.retrieval import EvidenceItem
    from app.services.topic_proposal import validate_coverage

    body = (
        "Unit {n}: topic list with enough words to be a real syllabus section, clearly substantive."
    )
    title, *units = [uuid4() for _ in range(6)]
    batch = [
        EvidenceItem(title, uuid4(), 1, "s.pdf", "syllabus", 1, 1, [], "Sample syllabus", "en", 1.0)
    ] + [
        EvidenceItem(cid, uuid4(), 1, "s.pdf", "syllabus", 1, 1, [], body.format(n=i), "en", 1.0)
        for i, cid in enumerate(units)
    ]

    def proposal(cited: list[Any]) -> TopicProposal:
        return TopicProposal(
            topics=[
                ProposedTopic(
                    title=f"T{i}",
                    parent_title=None,
                    citations=[CitationReference(chunk_id=cid, quote="topic list")],
                )
                for i, cid in enumerate(cited)
            ]
        )

    validate_coverage(proposal(units), batch)  # title chunk uncited: fine
    validate_coverage(proposal(units[:-1]), batch)  # one substantive uncited: tolerated
    with pytest.raises(ValueError, match="INCOMPLETE_TOPIC_COVERAGE"):
        validate_coverage(proposal(units[:2]), batch)


def test_retry_after_parsing() -> None:
    from app.providers.groq import retry_after_seconds

    assert retry_after_seconds(
        RuntimeError("Please try again in 9.47s. Need more")
    ) == pytest.approx(9.97)
    assert retry_after_seconds(RuntimeError("try again in 350ms")) == pytest.approx(0.85)
    assert retry_after_seconds(RuntimeError("no hint")) == 5.0
