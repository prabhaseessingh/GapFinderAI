"""Blueprint policy, validators, and the quiz/attempt lifecycle."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Attempt, Quiz, QuizQuestion
from app.schemas.quiz import GeneratedQuestion, QuestionOption, RubricCriterion
from app.schemas.topics import CitationReference
from app.services import quiz_generation
from app.services.quiz_generation import QuizGenerationFailed, run_generation, validate_generated
from app.services.quiz_policy import Leaf, Slot, UnitCandidate, allocate, build_blueprint
from app.services.retrieval import EvidenceBundle, EvidenceItem
from tests.factories import make_document, make_topic, make_workspace
from tests.helpers import auth_headers, make_student

# ---- blueprint policy (unit) ---------------------------------------------------------------------


def _unit(importance: int, position: int, leaves: int = 2) -> UnitCandidate:
    unit_id = uuid4()
    return UnitCandidate(
        unit_id,
        f"Unit {position}",
        importance,
        position,
        tuple(Leaf(uuid4(), f"U{position}-L{i}", 3, i) for i in range(leaves)),
    )


@pytest.mark.parametrize("count", [5, 10, 15])
def test_blueprint_is_exact_and_gives_every_tested_unit_two(count: int) -> None:
    units = [_unit(5, 0), _unit(3, 1), _unit(1, 2)]
    blueprint = build_blueprint(units, count)
    assert len(blueprint.slots) == count
    per_unit: dict[UUID, int] = {}
    for slot in blueprint.slots:
        per_unit[slot.unit_id] = per_unit.get(slot.unit_id, 0) + 1
    assert all(n >= 2 for n in per_unit.values())
    assert [s.position for s in blueprint.slots] == list(range(count))


def test_blueprint_types_follow_cognitive_level() -> None:
    blueprint = build_blueprint([_unit(3, 0), _unit(3, 1)], 10)
    for slot in blueprint.slots:
        if slot.cognitive_level == "recall":
            assert slot.question_type in {"mcq", "true_false"} and slot.max_score == 1
        else:
            assert slot.question_type == "short_answer" and slot.max_score > 1
    assert {s.question_type for s in blueprint.slots} == {"mcq", "true_false", "short_answer"}


def test_budget_tests_most_important_units_and_records_the_rest() -> None:
    units = [_unit(1, 0), _unit(5, 1), _unit(4, 2), _unit(2, 3)]
    blueprint = build_blueprint(units, 5)  # room for 2 units
    tested = {s.unit_title for s in blueprint.slots}
    assert tested == {"Unit 1", "Unit 2"}
    assert {n["title"] for n in blueprint.not_tested} == {"Unit 0", "Unit 3"}
    assert allocate(units, 5) == {units[1].topic_id: 3, units[2].topic_id: 2}


def test_units_without_evidence_are_never_tested() -> None:
    blueprint = build_blueprint([_unit(5, 0, leaves=0), _unit(1, 1)], 5)
    assert {s.unit_title for s in blueprint.slots} == {"Unit 1"}
    assert blueprint.not_tested == [
        {
            "topic_id": blueprint.not_tested[0]["topic_id"],
            "title": "Unit 0",
            "reason": "no_evidence",
        }
    ]
    with pytest.raises(ValueError):
        build_blueprint([_unit(5, 0, leaves=0)], 5)


# ---- validators (unit) ---------------------------------------------------------------------------

CHUNK = uuid4()
SOURCE = "Ohm's law states that the current through a conductor is proportional to the potential difference."
BUNDLE = EvidenceBundle(
    "ohm",
    ("notes",),
    [EvidenceItem(CHUNK, uuid4(), 1, "notes.txt", "notes", 1, 1, [], SOURCE, "en", 1.0)],
)


def _slot(qtype: str, level: str = "recall", score: float = 1.0) -> Slot:
    return Slot(0, uuid4(), "Electricity", uuid4(), "Ohm's law", level, qtype, score)


def _question(slot: Slot, bundle: EvidenceBundle = BUNDLE, **overrides: Any) -> GeneratedQuestion:
    quote = "current through a conductor is proportional"
    chunk_id = bundle.items[0].chunk_id
    base: dict[str, Any] = {
        "question_type": slot.question_type,
        "cognitive_level": slot.cognitive_level,
        "prompt": f"Question {uuid4().hex[:6]} about {slot.topic_title}: what does the law relate?",
        "options": None,
        "correct_option_id": None,
        "correct_boolean": None,
        "model_answer": None,
        "rubric": [],
        "max_score": slot.max_score,
        "explanation": "Because the notes say so.",
        "citations": [CitationReference(chunk_id=chunk_id, quote=quote)],
    }
    if slot.question_type == "mcq":
        base |= {
            "options": [QuestionOption(id=i, text=f"Option {i}") for i in "ABCD"],
            "correct_option_id": "B",
        }
    elif slot.question_type == "true_false":
        base |= {"correct_boolean": True}
    else:
        half = slot.max_score / 2
        base |= {
            "model_answer": "Current is proportional to voltage.",
            "rubric": [
                RubricCriterion(criterion="Names current", points=half),
                RubricCriterion(criterion="Names voltage", points=half),
            ],
        }
    return GeneratedQuestion(**(base | overrides))


def test_valid_questions_pass_all_types() -> None:
    validate_generated(_question(_slot("mcq")), _slot("mcq"), BUNDLE)
    validate_generated(_question(_slot("true_false")), _slot("true_false"), BUNDLE)
    short = _slot("short_answer", "understand", 3.0)
    validate_generated(_question(short), short, BUNDLE)


@pytest.mark.parametrize(
    ("slot", "overrides", "code"),
    [
        (
            _slot("mcq"),
            {
                "citations": [
                    CitationReference(chunk_id=uuid4(), quote="current through a conductor")
                ]
            },
            "CITATION_NOT_IN_EVIDENCE",
        ),
        (
            _slot("mcq"),
            {"citations": [CitationReference(chunk_id=CHUNK, quote="electrons are tiny planets")]},
            "CITATION_QUOTE_NOT_IN_SOURCE",
        ),
        (_slot("mcq"), {"correct_option_id": "E"}, "INVALID_MCQ_KEY"),
        (
            _slot("mcq"),
            {"options": [QuestionOption(id=i, text="Same") for i in "ABCD"]},
            "INVALID_MCQ_OPTIONS",
        ),
        (_slot("true_false"), {"correct_boolean": None}, "INVALID_TRUE_FALSE_KEY"),
        (
            _slot("short_answer", "apply", 4.0),
            {
                "rubric": [
                    RubricCriterion(criterion="One", points=1),
                    RubricCriterion(criterion="Two", points=1),
                ]
            },
            "RUBRIC_POINTS_MISMATCH",
        ),
        (_slot("mcq"), {"question_type": "true_false"}, "WRONG_QUESTION_TYPE"),
    ],
)
def test_invalid_questions_are_rejected(slot: Slot, overrides: dict[str, Any], code: str) -> None:
    with pytest.raises(ValueError, match=code):
        validate_generated(_question(slot, **overrides), slot, BUNDLE)


# ---- lifecycle (integration) ---------------------------------------------------------------------

NOTES = [
    "Refraction of light: Snell's law relates the angles of incidence and refraction through the refractive index of the media.",
    "Ohm's law states that the current through a conductor is proportional to the potential difference across it at constant temperature.",
    "Photosynthesis uses carbon dioxide, water and sunlight; chlorophyll absorbs light and the plant releases oxygen.",
]


def _fake_generate(
    _provider: Any, _quiz: Any, slot: Slot, bundle: EvidenceBundle, _avoid: Any
) -> GeneratedQuestion:
    item = bundle.items[0]
    words = item.original_quote.split()
    quote = " ".join(words[2:8])
    question = _question(
        slot,
        bundle,
        citations=[CitationReference(chunk_id=item.chunk_id, quote=quote)],
        prompt=f"Slot {slot.position}: explain {slot.topic_title} ({uuid4().hex[:8]})",
    )
    validate_generated(question, slot, bundle)  # the fake obeys the same gate as Groq output
    return question


@pytest.fixture()
def quiz_world(db: Session, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(quiz_generation, "_generate_slot", _fake_generate)
    student = make_student(db)
    ws = make_workspace(db, student)
    make_document(db, ws, "notes", chunks=NOTES, seed=20)
    light = make_topic(db, ws, "Light", status="approved")
    make_topic(db, ws, "Refraction Snell's law", status="approved", parent=light)
    electricity = make_topic(db, ws, "Electricity", status="approved")
    make_topic(db, ws, "Ohm's law current", status="approved", parent=electricity)
    make_topic(db, ws, "Photosynthesis", status="approved")
    return {"student": student, "ws": ws}


def _generate(
    db: Session, world: dict[str, Any], count: int = 10, minutes: int | None = None
) -> Quiz:
    quiz = Quiz(
        workspace_id=world["ws"].id,
        student_id=world["student"],
        state="blueprint_draft",
        question_count=count,
        locale="en",
        timer_mode="timed" if minutes else "untimed",
        time_limit_seconds=minutes * 60 if minutes else None,
        blueprint={},
        policy_version="test",
    )
    db.add(quiz)
    db.commit()
    run_generation(db, object(), quiz, None, lambda _q: [0.0] * 384)  # type: ignore[arg-type]
    db.refresh(quiz)
    return quiz


@pytest.mark.integration
@pytest.mark.parametrize("count", [5, 10, 15])
def test_generation_publishes_exact_count_with_valid_citations(
    db: Session, quiz_world: dict[str, Any], count: int
) -> None:
    quiz = _generate(db, quiz_world, count)
    questions = list(db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)))
    assert quiz.state == "ready" and len(questions) == count
    assert len({q.content_hash for q in questions}) == count
    assert quiz.blueprint["policy_version"] and len(quiz.blueprint["slots"]) == count


@pytest.mark.integration
def test_no_answer_material_means_insufficient_evidence(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quiz_generation, "_generate_slot", _fake_generate)
    student = make_student(db)
    ws = make_workspace(db, student)
    make_document(
        db, ws, "past_paper", chunks=NOTES, seed=30
    )  # past papers are never answer evidence
    make_topic(db, ws, "Ohm's law current", status="approved")
    quiz = Quiz(
        workspace_id=ws.id,
        student_id=student,
        question_count=5,
        locale="en",
        blueprint={},
        policy_version="t",
    )
    db.add(quiz)
    db.commit()
    with pytest.raises(QuizGenerationFailed, match="INSUFFICIENT_WORKSPACE_EVIDENCE"):
        run_generation(db, object(), quiz, None, lambda _q: [0.0] * 384)  # type: ignore[arg-type]


@pytest.mark.integration
def test_attempt_hides_key_until_submit_then_locks(
    client: Any, db: Session, quiz_world: dict[str, Any]
) -> None:
    quiz = _generate(db, quiz_world, 5)
    headers = auth_headers(quiz_world["student"])
    attempt = client.post(f"/quizzes/{quiz.id}/attempts", headers=headers).json()
    raw = str(attempt)
    for secret in (
        "correct_option_id",
        "correct_boolean",
        "model_answer",
        "rubric",
        "citations",
        "explanation",
    ):
        assert secret not in raw
    first = attempt["questions"][0]
    answer = (
        "A"
        if first["question_type"] == "mcq"
        else True
        if first["question_type"] == "true_false"
        else "my answer"
    )
    path = f"/attempts/{attempt['id']}/responses/{first['id']}"
    assert client.put(path, json={"answer": answer}, headers=headers).status_code == 204
    assert client.put(path, json={"answer": 42}, headers=headers).status_code == 422
    again = client.post(f"/quizzes/{quiz.id}/attempts", headers=headers).json()
    assert (
        again["id"] == attempt["id"] and again["answers"][first["id"]] == answer
    )  # resume, autosaved

    submitted = client.post(f"/attempts/{attempt['id']}/submit", headers=headers).json()
    assert submitted["state"] == "submitted" and submitted["submit_reason"] == "student"
    assert (
        "correct_option_id" in submitted["questions"][0] and submitted["questions"][0]["citations"]
    )
    assert (
        client.post(f"/attempts/{attempt['id']}/submit", headers=headers).json()["submitted_at"]
        == submitted["submitted_at"]
    )
    assert client.put(path, json={"answer": answer}, headers=headers).status_code == 409
    assert client.post(f"/quizzes/{quiz.id}/attempts", headers=headers).status_code == 409


@pytest.mark.integration
def test_timed_attempt_auto_submits_at_deadline(
    client: Any, db: Session, quiz_world: dict[str, Any]
) -> None:
    quiz = _generate(db, quiz_world, 5, minutes=1)
    headers = auth_headers(quiz_world["student"])
    attempt = client.post(f"/quizzes/{quiz.id}/attempts", headers=headers).json()
    assert attempt["deadline_at"] is not None
    past = datetime.now(UTC) - timedelta(minutes=5)
    db.execute(
        text("UPDATE attempts SET started_at = :s, deadline_at = :d WHERE id = :id"),
        {"s": past - timedelta(minutes=1), "d": past, "id": attempt["id"]},
    )
    db.commit()
    question = attempt["questions"][0]
    late = client.put(
        f"/attempts/{attempt['id']}/responses/{question['id']}",
        json={"answer": None},
        headers=headers,
    )
    assert late.status_code == 409
    view = client.get(f"/attempts/{attempt['id']}", headers=headers).json()
    assert (
        view["state"] == "submitted"
        and view["submit_reason"] == "time_limit"
        and view["elapsed_seconds"] == 60
    )


@pytest.mark.integration
def test_other_students_cannot_touch_a_quiz(
    client: Any, db: Session, quiz_world: dict[str, Any]
) -> None:
    quiz = _generate(db, quiz_world, 5)
    owner = auth_headers(quiz_world["student"])
    attempt = client.post(f"/quizzes/{quiz.id}/attempts", headers=owner).json()
    stranger = auth_headers(make_student(db))
    for method, path in [
        ("GET", f"/quizzes/{quiz.id}"),
        ("POST", f"/quizzes/{quiz.id}/attempts"),
        ("GET", f"/attempts/{attempt['id']}"),
        ("POST", f"/attempts/{attempt['id']}/submit"),
        ("GET", f"/quizzes/workspace/{quiz.workspace_id}"),
    ]:
        assert client.request(method, path, headers=stranger).status_code == 404, path
    assert (
        db.scalar(select(Attempt.state).where(Attempt.id == UUID(attempt["id"]))) == "in_progress"
    )


@pytest.mark.integration
def test_create_quiz_requires_approved_topics_and_answer_material(client: Any, db: Session) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    headers = auth_headers(student)
    body = {"workspace_id": str(ws.id), "question_count": 10}
    assert (
        client.post("/quizzes", json=body, headers=headers).json()["error"]["code"]
        == "INVALID_STATE"
    )
    make_topic(db, ws, "Cells", status="approved")
    no_notes = client.post("/quizzes", json=body, headers=headers).json()["error"]
    assert (
        no_notes["code"] == "INSUFFICIENT_WORKSPACE_EVIDENCE"
        and no_notes["nextAction"] == "upload_or_select_material"
    )
    assert (
        client.post("/quizzes", json=body | {"question_count": 7}, headers=headers).status_code
        == 422
    )
    assert (
        client.post("/quizzes", json=body | {"timer_mode": "timed"}, headers=headers).status_code
        == 422
    )
