from uuid import uuid4

import pytest

from app.schemas.topics import CitationReference, ProposedTopic, TopicProposal
from app.schemas.workspaces import CreateWorkspaceRequest
from app.services.documents import _storage_key
from app.services.retrieval import EvidenceItem, reciprocal_rank_fusion
from app.services.states import require_document_transition
from app.services.storage import parse_object_metadata
from app.services.topics import validate_proposal


def test_document_state_machine_rejects_skips() -> None:
    require_document_transition("uploaded", "scanning")
    with pytest.raises(ValueError):
        require_document_transition("uploaded", "ready")


def test_storage_path_is_workspace_scoped_and_immutable_versioned() -> None:
    workspace_id, document_id = uuid4(), uuid4()
    path = _storage_key(workspace_id, document_id, "my notes.pdf")
    assert path == f"workspaces/{workspace_id}/documents/{document_id}/v1/my notes.pdf"


def test_storage_metadata_accepts_object_and_single_item_list_shapes() -> None:
    item = {"name": "path.pdf", "metadata": {"size": 42, "mimetype": "application/pdf"}}
    assert parse_object_metadata(item, "path.pdf").size == 42  # type: ignore[union-attr]
    assert parse_object_metadata([item], "path.pdf").size == 42  # type: ignore[union-attr]


def test_workspace_title_cannot_be_whitespace_only() -> None:
    with pytest.raises(ValueError, match="cannot be blank"):
        CreateWorkspaceRequest(title="   ", selected_locale="en")


def test_topic_proposal_rejects_a_quote_not_present_in_syllabus_evidence() -> None:
    chunk_id = uuid4()
    evidence = [
        EvidenceItem(
            chunk_id, uuid4(), 1, "syllabus.txt", "syllabus", 1, 1, [], "Cell biology", "en", 1.0
        )
    ]
    proposal = TopicProposal(
        topics=[
            ProposedTopic(
                title="Cells",
                parent_title=None,
                citations=[CitationReference(chunk_id=chunk_id, quote="Invented quote")],
            )
        ]
    )
    with pytest.raises(ValueError, match="INVALID_TOPIC_CITATION"):
        validate_proposal(proposal, evidence)


def test_topic_proposal_accepts_normalized_source_quote() -> None:
    chunk_id = uuid4()
    evidence = [
        EvidenceItem(
            chunk_id,
            uuid4(),
            1,
            "syllabus.txt",
            "syllabus",
            1,
            1,
            [],
            "Cell   biology\nintroduction",
            "en",
            1.0,
        )
    ]
    proposal = TopicProposal(
        topics=[
            ProposedTopic(
                title="Cells",
                parent_title=None,
                citations=[CitationReference(chunk_id=chunk_id, quote="Cell biology introduction")],
            )
        ]
    )
    validate_proposal(proposal, evidence)


def test_hybrid_rank_fusion_rewards_evidence_found_by_both_retrievers() -> None:
    lexical_only, vector_only, shared = uuid4(), uuid4(), uuid4()
    fused = reciprocal_rank_fusion(
        [
            [(lexical_only, 0.9), (shared, 0.8)],
            [(vector_only, 0.9), (shared, 0.8)],
        ]
    )
    assert fused[0][0] == shared
