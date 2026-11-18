"""Cited diagnostic quiz generation.

blueprint (deterministic) -> textbook/notes evidence per slot -> Groq (quality model) ->
schema + citation + answer/option/rubric + topic + dedupe validation -> persist.
Past papers inform importance only; they are never answer evidence. Invalid output is never
published: a slot that cannot be validated fails the quiz with a clear insufficiency code.
"""

import hashlib
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Quiz, QuizQuestion, Topic, TopicChunkLink
from app.providers.groq import (
    UNTRUSTED_SOURCE_RULE,
    AiCallContext,
    GroqOutputRejected,
    GroqProvider,
    source_block,
)
from app.schemas.quiz import GeneratedQuestion
from app.services.quiz_policy import Blueprint, Leaf, Slot, UnitCandidate, build_blueprint
from app.services.retrieval import (
    EvidenceBundle,
    normalize_text,
    quote_in_source,
    retrieve_evidence,
)
from app.services.translation import LOCALE_DESCRIPTION

logger = logging.getLogger("gapfinder.quiz")
QUESTION_PROMPT_VERSION = "quiz-question-v1"
ANSWER_ROLES = ("textbook", "notes")
EVIDENCE_PER_SLOT = 6
# Decision (Groq free tier, 8k tokens/min per model): objective questions on the fast model,
# short answers on the quality model; one sequential lane per model so both budgets run in parallel.
TIER_BY_TYPE: dict[str, Literal["fast", "quality"]] = {
    "mcq": "fast",
    "true_false": "fast",
    "short_answer": "quality",
}

LEVEL_GUIDE = {
    "recall": "recall: tests whether the student remembers a fact, term or definition stated in the evidence",
    "understand": "understand: asks the student to explain a concept, cause or relationship in their own words",
    "apply": "apply: asks the student to use a stated rule, formula or process on a small new case, solvable only with the evidence",
}
TYPE_RULES = {
    "mcq": "mcq: exactly 4 options with ids A, B, C, D; exactly one correct (correct_option_id); plausible distractors that the evidence shows are wrong; correct_boolean = null; model_answer = null; rubric = []; max_score = 1",
    "true_false": "true_false: a single clear statement; correct_boolean true or false; options = null; correct_option_id = null; model_answer = null; rubric = []; max_score = 1",
    "short_answer": "short_answer: options = null; correct_option_id = null; correct_boolean = null; model_answer = a concise ideal answer; rubric = 2-4 criteria whose points sum exactly to max_score",
}


class QuizGenerationFailed(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def content_hash(prompt: str) -> str:
    return hashlib.sha256(normalize_text(prompt).casefold().encode("utf-8")).hexdigest()


# ---- candidates & evidence -----------------------------------------------------------------------


EvidenceFn = Callable[[str], EvidenceBundle]


def _topic_query(session: Session, topic: Topic, unit: Topic | None) -> str:
    quotes = list(
        session.scalars(
            select(TopicChunkLink.quote)
            .where(TopicChunkLink.topic_id == topic.id, TopicChunkLink.quote.is_not(None))
            .limit(3)
        )
    )
    parts = [
        topic.title,
        unit.title if unit and unit.id != topic.id else "",
        *[q for q in quotes if q],
    ]
    return " ".join(p for p in parts if p)


@dataclass
class Candidates:
    units: list[UnitCandidate]
    evidence: dict[UUID, EvidenceBundle]


def collect_candidates(
    session: Session, workspace_id: UUID, topic_ids: Sequence[UUID] | None, evidence_for: EvidenceFn
) -> Candidates:
    topics = list(
        session.scalars(
            select(Topic).where(Topic.workspace_id == workspace_id, Topic.status == "approved")
        )
    )
    if topic_ids:
        wanted = set(topic_ids)
        # A selected sub-topic brings its unit; a selected unit brings its sub-topics.
        topics = [
            t
            for t in topics
            if t.id in wanted
            or t.parent_id in wanted
            or any(c.id in wanted and c.parent_id == t.id for c in topics)
        ]
    by_id = {t.id: t for t in topics}
    units = [t for t in topics if t.parent_id is None or t.parent_id not in by_id]
    evidence: dict[UUID, EvidenceBundle] = {}
    candidates: list[UnitCandidate] = []
    for unit in units:
        children = [t for t in topics if t.parent_id == unit.id]
        leaves: list[Leaf] = []
        for topic in children or [unit]:
            bundle = evidence_for(_topic_query(session, topic, unit))
            if not bundle.insufficient:
                evidence[topic.id] = bundle
                leaves.append(Leaf(topic.id, topic.title, topic.importance, topic.position))
        if not leaves and children:  # sub-topics unsupported: fall back to unit-level evidence
            bundle = evidence_for(_topic_query(session, unit, unit))
            if not bundle.insufficient:
                evidence[unit.id] = bundle
                leaves.append(Leaf(unit.id, unit.title, unit.importance, unit.position))
        candidates.append(
            UnitCandidate(unit.id, unit.title, unit.importance, unit.position, tuple(leaves))
        )
    return Candidates(candidates, evidence)


# ---- validation ----------------------------------------------------------------------------------


def validate_generated(question: GeneratedQuestion, slot: Slot, bundle: EvidenceBundle) -> None:
    if question.question_type != slot.question_type:
        raise ValueError("WRONG_QUESTION_TYPE")
    if question.cognitive_level != slot.cognitive_level:
        raise ValueError("WRONG_COGNITIVE_LEVEL")
    for citation in question.citations:
        item = bundle.get(citation.chunk_id)
        if item is None:
            raise ValueError("CITATION_NOT_IN_EVIDENCE")
        if len(normalize_text(citation.quote)) < 12 or not quote_in_source(
            citation.quote, item.original_quote
        ):
            raise ValueError("CITATION_QUOTE_NOT_IN_SOURCE")
    if question.question_type == "mcq":
        options = question.options or []
        ids = [o.id for o in options]
        texts = {normalize_text(o.text).casefold() for o in options}
        if len(options) != 4 or sorted(ids) != ["A", "B", "C", "D"] or len(texts) != 4:
            raise ValueError("INVALID_MCQ_OPTIONS")
        if question.correct_option_id not in ids or question.correct_boolean is not None:
            raise ValueError("INVALID_MCQ_KEY")
        if question.rubric or question.max_score != 1:
            raise ValueError("INVALID_OBJECTIVE_SCORING")
    elif question.question_type == "true_false":
        if question.correct_boolean is None or question.options or question.correct_option_id:
            raise ValueError("INVALID_TRUE_FALSE_KEY")
        if question.rubric or question.max_score != 1:
            raise ValueError("INVALID_OBJECTIVE_SCORING")
    else:
        if not question.model_answer or not 2 <= len(question.rubric) <= 4:
            raise ValueError("INVALID_SHORT_ANSWER_RUBRIC")
        if abs(sum(c.points for c in question.rubric) - question.max_score) > 0.01:
            raise ValueError("RUBRIC_POINTS_MISMATCH")
        if abs(question.max_score - slot.max_score) > 0.01:
            raise ValueError("WRONG_MAX_SCORE")
        if question.options or question.correct_option_id or question.correct_boolean is not None:
            raise ValueError("INVALID_SHORT_ANSWER_KEY")


# ---- generation ----------------------------------------------------------------------------------


def _generate_slot(
    provider: GroqProvider, quiz: Quiz, slot: Slot, bundle: EvidenceBundle, avoid: Sequence[str]
) -> GeneratedQuestion:
    language = LOCALE_DESCRIPTION.get(quiz.locale, "English")
    avoid_text = "\n".join(f"- {p}" for p in avoid) or "- (none)"
    return provider.structured(
        AiCallContext(
            "generate_question",
            QUESTION_PROMPT_VERSION,
            quiz.student_id,
            quiz.workspace_id,
            bundle.chunk_ids,
        ),
        output=GeneratedQuestion,
        tier=TIER_BY_TYPE[slot.question_type],
        attempts=3,
        system=f"You write fair diagnostic exam questions strictly from supplied study material. {UNTRUSTED_SOURCE_RULE}",
        user=(
            f'Write ONE question about the topic "{slot.topic_title}" (unit "{slot.unit_title}").\n'
            f"Cognitive level — {LEVEL_GUIDE[slot.cognitive_level]}.\n"
            f"Question type — {TYPE_RULES[slot.question_type]}. max_score = {slot.max_score:g}.\n"
            f'Set question_type = "{slot.question_type}" and cognitive_level = "{slot.cognitive_level}".\n'
            "The correct answer MUST be fully supported by the sources; never rely on outside knowledge. "
            "Do not reveal the answer in the prompt. "
            f"Write prompt, options, model_answer, rubric and explanation in {language}. "
            "citations: 1-3 items, each with the chunk_id of a source and `quote` copied EXACTLY from that "
            "source in its original language (at least a full phrase) that proves the correct answer. "
            "explanation: why the answer is correct, based on the quoted evidence.\n"
            f"Do not repeat or paraphrase these questions already in this quiz:\n{avoid_text}\n\n"
            + source_block(
                [
                    {
                        "chunk_id": str(i.chunk_id),
                        "file": i.document_name,
                        "page": i.page_start,
                        "text": i.original_quote,
                    }
                    for i in bundle.items
                ]
            )
        ),
        validate=lambda q: validate_generated(q, slot, bundle),
    )


ProgressFn = Callable[[int, int], None]


def generate_questions(
    provider: GroqProvider,
    quiz: Quiz,
    blueprint: Blueprint,
    evidence: dict[UUID, EvidenceBundle],
    progress: ProgressFn | None = None,
) -> list[tuple[Slot, GeneratedQuestion]]:
    """One sequential lane per model tier (both rate budgets used at once); later questions in a
    unit are told which prompts already exist so they do not repeat them."""
    lanes: dict[str, list[Slot]] = {}
    for slot in blueprint.slots:
        lanes.setdefault(TIER_BY_TYPE[slot.question_type], []).append(slot)
    lock = Lock()
    by_unit: dict[UUID, list[str]] = {}
    results: list[tuple[Slot, GeneratedQuestion]] = []

    def run_lane(slots: list[Slot]) -> None:
        for slot in slots:
            with lock:
                avoid = list(by_unit.get(slot.unit_id, []))
            question = _generate_slot(provider, quiz, slot, evidence[slot.topic_id], avoid)
            if content_hash(question.prompt) in {content_hash(p) for p in avoid}:
                question = _generate_slot(
                    provider, quiz, slot, evidence[slot.topic_id], avoid + [question.prompt]
                )
            with lock:
                by_unit.setdefault(slot.unit_id, []).append(question.prompt)
                results.append((slot, question))
                done = len(results)
            if progress:
                progress(done, len(blueprint.slots))

    with ThreadPoolExecutor(max_workers=max(1, len(lanes))) as pool:
        for future in [pool.submit(run_lane, slots) for slots in lanes.values()]:
            future.result()  # re-raise the first lane failure
    return sorted(results, key=lambda pair: pair[0].position)


def persist_questions(
    session: Session, quiz: Quiz, generated: list[tuple[Slot, GeneratedQuestion]]
) -> None:
    seen: set[str] = set()
    for slot, question in generated:
        digest = content_hash(question.prompt)
        if digest in seen:
            raise QuizGenerationFailed("DUPLICATE_QUESTIONS")
        seen.add(digest)
        if question.question_type == "mcq":
            key: object = {"option_id": question.correct_option_id}
        elif question.question_type == "true_false":
            key = {"boolean": question.correct_boolean}
        else:
            key = {"model_answer": question.model_answer}
        session.add(
            QuizQuestion(
                quiz_id=quiz.id,
                workspace_id=quiz.workspace_id,
                topic_id=slot.topic_id,
                topic_title=slot.topic_title,
                position=slot.position,
                question_type=question.question_type,
                cognitive_level=question.cognitive_level,
                prompt=question.prompt.strip(),
                options=[o.model_dump() for o in question.options] if question.options else None,
                correct_answer=key,
                rubric=[c.model_dump() for c in question.rubric],
                explanation=question.explanation,
                max_score=question.max_score,
                citations=[
                    {"chunk_id": str(c.chunk_id), "quote": c.quote} for c in question.citations
                ],
                content_hash=digest,
            )
        )


def run_generation(
    session: Session,
    provider: GroqProvider,
    quiz: Quiz,
    topic_ids: Sequence[UUID] | None,
    embed: Callable[[str], list[float]],
    progress: ProgressFn | None = None,
) -> int:
    """Blueprint (stored first) -> generation -> validated persistence. Returns question count."""

    def evidence_for(query: str) -> EvidenceBundle:
        return retrieve_evidence(
            session,
            quiz.student_id,
            quiz.workspace_id,
            query,
            query_embedding=embed(query),
            material_roles=ANSWER_ROLES,
            limit=EVIDENCE_PER_SLOT,
        )

    candidates = collect_candidates(session, quiz.workspace_id, topic_ids, evidence_for)
    try:
        blueprint = build_blueprint(candidates.units, quiz.question_count)
    except ValueError as error:
        raise QuizGenerationFailed("INSUFFICIENT_WORKSPACE_EVIDENCE") from error
    quiz.blueprint = blueprint.as_json()
    quiz.state = "generating"
    quiz.updated_at = func.now()
    session.commit()
    try:
        generated = generate_questions(provider, quiz, blueprint, candidates.evidence, progress)
    except GroqOutputRejected as error:
        raise QuizGenerationFailed(f"QUESTION_REJECTED:{error.code}"[:80]) from error
    if len(generated) != quiz.question_count:
        raise QuizGenerationFailed("WRONG_QUESTION_COUNT")
    persist_questions(session, quiz, generated)
    quiz.state = "ready"
    quiz.failure_code = None
    quiz.updated_at = func.now()
    session.commit()
    return len(generated)
