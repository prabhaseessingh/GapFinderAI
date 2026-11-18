"""Workspace-scoped hybrid retrieval.

Filters (student, workspace, ready state, role) are applied *before* ranking. Lexical (FTS) and
vector (pgvector cosine) candidates are fused with reciprocal-rank fusion; a candidate is only
admissible when it matched lexically or cleared the calibrated vector-similarity threshold.
An empty bundle is a deliberate refusal signal: callers must return INSUFFICIENT_WORKSPACE_EVIDENCE.
"""

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document
from app.services.workspaces import require_workspace_owner

RETRIEVAL_POLICY_VERSION = "retrieval-2026-11-18"
RRF_K = 60
# Vector matches must clear a floor AND sit within a margin of the query's best match. Calibrated for
# Qwen3-Embedding-0.6B @384 on a 16-query en/hi/pa/te check: cross-language scores (e.g. Telugu question,
# English notes) run lower than same-language ones, so no single fixed cut-off works — fixed 0.42 kept
# 5/10 cross-language answers, fixed 0.30 let in 32% unrelated passages; floor 0.28-0.32 + margin 0.06
# kept 6/6 English and 8/10 cross-language answers with 4% unrelated. 0.31 also drops in-domain
# near-misses measured live (Ohm's law vs a maths syllabus: 0.296-0.305) while keeping live Punjabi /
# Telugu answers (0.326 / 0.330). Off-topic questions (~0.14) get no evidence. Anything that still slips
# through is caught by the exact-quote grounding gate downstream. Lexical matches are fused via RRF.
MIN_VECTOR_SIMILARITY = 0.31
VECTOR_MARGIN = 0.06
MAX_RESULTS = 12
ALL_ROLES: tuple[str, ...] = ("syllabus", "textbook", "notes", "past_paper")
READY_STATES: tuple[str, ...] = ("ready",)


@dataclass(frozen=True)
class EvidenceItem:
    chunk_id: UUID
    document_id: UUID
    document_version: int
    document_name: str
    material_role: str
    page_start: int | None
    page_end: int | None
    heading_path: list[str]
    original_quote: str
    source_language: str
    score: float
    translated_quote: str | None = None


@dataclass(frozen=True)
class EvidenceBundle:
    query: str
    roles: tuple[str, ...]
    items: list[EvidenceItem] = field(default_factory=list)
    policy_version: str = RETRIEVAL_POLICY_VERSION

    @property
    def insufficient(self) -> bool:
        return not self.items

    @property
    def chunk_ids(self) -> list[UUID]:
        return [item.chunk_id for item in self.items]

    def get(self, chunk_id: UUID) -> EvidenceItem | None:
        return next((item for item in self.items if item.chunk_id == chunk_id), None)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def quote_in_source(quote: str, source: str) -> bool:
    """Citation rule: the quote must be a whitespace-normalised substring of the chunk."""
    needle = normalize_text(quote).casefold()
    return bool(needle) and needle in normalize_text(source).casefold()


def keep_vector_matches(
    scored: Sequence[tuple[UUID, float]],
    floor: float = MIN_VECTOR_SIMILARITY,
    margin: float = VECTOR_MARGIN,
) -> list[tuple[UUID, float]]:
    """Calibrated gate for semantic candidates: above the floor and close to the best match."""
    if not scored:
        return []
    best = max(score for _, score in scored)
    return [(cid, score) for cid, score in scored if score >= floor and score >= best - margin]


def reciprocal_rank_fusion(
    ranked_lists: Iterable[Sequence[tuple[UUID, float]]], *, k: int = RRF_K
) -> list[tuple[UUID, float]]:
    """Fuse ranked lexical/vector candidates without comparing incompatible scores."""
    totals: dict[UUID, float] = {}
    for ranked in ranked_lists:
        for rank, (chunk_id, _score) in enumerate(ranked, start=1):
            totals[chunk_id] = totals.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(totals.items(), key=lambda item: (-item[1], str(item[0])))


def apply_diversity(ordered: Sequence[tuple[UUID, UUID]], limit: int) -> list[UUID]:
    """Cap chunks per document so one file cannot crowd out others; backfill if needed.

    `ordered` holds (chunk_id, document_id) best-first.
    """
    documents = {document_id for _, document_id in ordered}
    per_document = limit if len(documents) <= 1 else max(2, math.ceil(limit / 2))
    taken: list[UUID] = []
    counts: dict[UUID, int] = {}
    deferred: list[UUID] = []
    for chunk_id, document_id in ordered:
        if counts.get(document_id, 0) < per_document:
            taken.append(chunk_id)
            counts[document_id] = counts.get(document_id, 0) + 1
        else:
            deferred.append(chunk_id)
        if len(taken) == limit:
            return taken
    return (taken + deferred)[:limit]


def _evidence_from_rows(
    rows: Iterable[tuple[Chunk, Document]], scores: dict[UUID, float]
) -> list[EvidenceItem]:
    return [
        EvidenceItem(
            chunk_id=chunk.id,
            document_id=document.id,
            document_version=document.version,
            document_name=document.filename,
            material_role=document.material_role,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            heading_path=list(chunk.heading_path or []),
            original_quote=chunk.text_content,
            source_language=chunk.source_language,
            score=scores.get(chunk.id, 0.0),
        )
        for chunk, document in rows
    ]


_FILTER = """
    FROM chunks AS c
    JOIN documents AS d ON d.id = c.document_id
    WHERE c.workspace_id = :workspace_id
      AND d.workspace_id = :workspace_id
      AND d.student_id = :student_id
      AND d.state = ANY(CAST(:states AS text[]))
      AND d.material_role = ANY(CAST(:roles AS text[]))
"""


def retrieve_evidence(
    session: Session,
    student_id: UUID,
    workspace_id: UUID,
    query: str,
    *,
    query_embedding: Sequence[float] | None = None,
    material_roles: Sequence[str] = ALL_ROLES,
    limit: int = MAX_RESULTS,
    min_vector_similarity: float = MIN_VECTOR_SIMILARITY,
    states: Sequence[str] = READY_STATES,
) -> EvidenceBundle:
    require_workspace_owner(session, student_id, workspace_id)
    limit = max(1, min(limit, MAX_RESULTS))
    roles = tuple(material_roles)
    cleaned_query = normalize_text(query)
    if not cleaned_query or not roles:
        return EvidenceBundle(cleaned_query, roles)

    params = {
        "workspace_id": workspace_id,
        "student_id": student_id,
        "roles": list(roles),
        "states": list(states),
        "candidate_limit": max(limit * 4, 24),
    }
    lexical_rows = session.execute(
        text(
            "SELECT c.id, ts_rank_cd(to_tsvector('simple', c.text_content), "
            "websearch_to_tsquery('simple', :query)) AS score"
            + _FILTER
            + " AND to_tsvector('simple', c.text_content) @@ websearch_to_tsquery('simple', :query)"
            " ORDER BY score DESC, c.id LIMIT :candidate_limit"
        ),
        params | {"query": cleaned_query},
    ).all()
    ranked: list[list[tuple[UUID, float]]] = [[(row.id, float(row.score)) for row in lexical_rows]]

    if query_embedding:
        vector = "[" + ",".join(f"{value:.8f}" for value in query_embedding) + "]"
        vector_rows = session.execute(
            text(
                "SELECT c.id, 1 - (c.embedding <=> CAST(:embedding AS vector)) AS score"
                + _FILTER
                + " AND c.embedding IS NOT NULL"
                " ORDER BY c.embedding <=> CAST(:embedding AS vector), c.id LIMIT :candidate_limit"
            ),
            params | {"embedding": vector},
        ).all()
        ranked.append(
            keep_vector_matches(
                [(row.id, float(row.score)) for row in vector_rows], min_vector_similarity
            )
        )

    fused = reciprocal_rank_fusion(ranked)
    if not fused:
        return EvidenceBundle(cleaned_query, roles)
    scores = dict(fused)
    rows = session.execute(
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.id.in_(list(scores)),
            Chunk.workspace_id == workspace_id,
            Document.workspace_id == workspace_id,
            Document.student_id == student_id,
            Document.state.in_(list(states)),
        )
    ).all()
    document_of = {chunk.id: document.id for chunk, document in rows}
    ordered = [
        (chunk_id, document_of[chunk_id]) for chunk_id, _ in fused if chunk_id in document_of
    ]
    selected = apply_diversity(ordered, limit)
    by_id = {item.chunk_id: item for item in _evidence_from_rows(rows, scores)}
    return EvidenceBundle(cleaned_query, roles, [by_id[chunk_id] for chunk_id in selected])


def retrieve_role_evidence(
    session: Session,
    student_id: UUID,
    workspace_id: UUID,
    role: str,
    *,
    states: Sequence[str] = READY_STATES,
    document_ids: Sequence[UUID] | None = None,
) -> list[EvidenceItem]:
    """Every chunk of the owned, processed documents of one role, in reading order."""
    require_workspace_owner(session, student_id, workspace_id)
    query = (
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.workspace_id == workspace_id,
            Document.workspace_id == workspace_id,
            Document.student_id == student_id,
            Document.material_role == role,
            Document.state.in_(list(states)),
        )
        .order_by(Document.created_at, Document.id, Chunk.chunk_index)
    )
    if document_ids is not None:
        query = query.where(Document.id.in_(list(document_ids)))
    rows = session.execute(query).all()
    return _evidence_from_rows(rows, {chunk.id: 1.0 for chunk, _ in rows})


def retrieve_syllabus_evidence(
    session: Session,
    student_id: UUID,
    workspace_id: UUID,
    *,
    states: Sequence[str] = READY_STATES,
) -> list[EvidenceItem]:
    """All ready syllabus chunks (no silent truncation; callers batch for the model)."""
    return retrieve_role_evidence(session, student_id, workspace_id, "syllabus", states=states)
