"""Syllabus → cited draft topic map. Invalid model output never reaches student-visible topics."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.providers.groq import UNTRUSTED_SOURCE_RULE, AiCallContext, GroqProvider, source_block
from app.schemas.topics import TopicProposal
from app.services.retrieval import EvidenceItem, normalize_text, retrieve_syllabus_evidence
from app.services.topics import (
    batch_evidence,
    merge_proposals,
    replace_draft_proposal,
    validate_proposal,
)

PROPOSAL_PROMPT_VERSION = "propose-topics-v3"
# Share of syllabus chunks in a batch that must be cited, so a model that stops early is retried.
MIN_CHUNK_COVERAGE = 0.8
MIN_SUBSTANTIVE_CHARS = 80


class InsufficientSyllabusEvidence(RuntimeError):
    pass


def validate_coverage(proposal: TopicProposal, batch: Sequence[EvidenceItem]) -> None:
    """Reject maps that stop early. Only substantive chunks count (a bare title or heading has
    nothing to cite); a few uncited chunks (admin text) are tolerated."""
    validate_proposal(proposal, batch)
    cited = {c.chunk_id for topic in proposal.topics for c in topic.citations}
    substantive = [
        item for item in batch if len(normalize_text(item.original_quote)) >= MIN_SUBSTANTIVE_CHARS
    ]
    uncited = sum(1 for item in substantive if item.chunk_id not in cited)
    if uncited > max(1, int((1 - MIN_CHUNK_COVERAGE) * len(substantive))):
        raise ValueError("INCOMPLETE_TOPIC_COVERAGE")


def propose_topic_map(
    session: Session,
    provider: GroqProvider,
    student_id: UUID,
    workspace_id: UUID,
    *,
    states: Sequence[str] = ("mapping", "ready"),
) -> int:
    evidence = retrieve_syllabus_evidence(session, student_id, workspace_id, states=states)
    if not evidence:
        raise InsufficientSyllabusEvidence("INSUFFICIENT_WORKSPACE_EVIDENCE")
    proposals: list[TopicProposal] = []
    for batch in batch_evidence(evidence):
        proposals.append(
            provider.structured(
                AiCallContext(
                    "propose_topics",
                    PROPOSAL_PROMPT_VERSION,
                    student_id,
                    workspace_id,
                    [item.chunk_id for item in batch],
                ),
                output=TopicProposal,
                attempts=3,
                system=f"You turn a student's syllabus into a topic map. {UNTRUSTED_SOURCE_RULE}",
                user=(
                    "Build a topic map ONLY from the syllabus sources below. Use the syllabus's own "
                    "topic names where possible. Produce at most two levels: a topic may name only a "
                    "top-level topic as parent_title (null for top-level). Every topic needs 1–6 "
                    "citations; each citation gives the chunk_id of a source and `quote`, a short "
                    "phrase copied EXACTLY from that source that names or describes the topic. Skip "
                    "administrative text (dates, grading policy, contact details).\n\n"
                    + source_block(
                        [
                            {
                                "chunk_id": str(i.chunk_id),
                                "page": i.page_start,
                                "heading": " > ".join(i.heading_path),
                                "text": i.original_quote,
                            }
                            for i in batch
                        ]
                    )
                ),
                validate=lambda proposal, b=batch: validate_coverage(proposal, b),  # type: ignore[misc]
            )
        )
    return replace_draft_proposal(session, workspace_id, merge_proposals(proposals), evidence)
