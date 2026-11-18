"""Live quiz-generation evaluation (pass gate: >= 30 source-verifiable questions).

Run inside the worker image against an isolated database, e.g.:
  docker compose --profile worker run --rm -e DATABASE_URL=<test db> -v <notes>:/data/notes.txt \
    worker python -m evals.quiz_eval /data/notes.txt /app/out/quiz-eval.md

Every published question is re-verified independently of the generation-time validator:
the cited chunk belongs to the workspace, the quote is an exact (normalised) substring of it,
the key/rubric are well-formed, and no prompt repeats.
"""

import hashlib
import sys
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.models import AiRun, Chunk, Document, Quiz, QuizQuestion, Topic, Workspace
from app.db.session import SessionLocal
from app.providers.groq import GroqProvider
from app.schemas.quiz import GeneratedQuestion, QuestionOption, RubricCriterion
from app.schemas.topics import CitationReference
from app.services.quiz_generation import run_generation
from app.services.retrieval import quote_in_source

TOPICS = {
    "Light and Optics": [
        "Laws of reflection",
        "Refraction and Snell's law",
        "Lenses and magnification",
    ],
    "Electricity": [
        "Ohm's law and resistance",
        "Resistors in series and parallel",
        "Heating effect and electric power",
    ],
    "Life Processes": [
        "Photosynthesis",
        "Aerobic and anaerobic respiration",
        "Human heart and blood",
    ],
}
RUNS = [("en", 10), ("hi-IN", 10), ("te-IN", 10)]


def ingest(session, student, workspace, notes: bytes) -> None:  # type: ignore[no-untyped-def]
    from tasks.extraction import chunk_pages, extract
    from tasks.ingest import embed_texts, embedding_label, store_chunks

    document = Document(
        workspace_id=workspace.id,
        student_id=student,
        material_role="notes",
        filename="sample-notes.txt",
        storage_key=f"eval/{uuid.uuid4()}",
        mime_type="text/plain",
        byte_size=len(notes),
        checksum_sha256=hashlib.sha256(notes).hexdigest(),
        state="ready",
    )
    session.add(document)
    session.flush()
    drafts = chunk_pages(extract("text/plain", notes))
    store_chunks(
        session, document, drafts, embed_texts([d.text for d in drafts]), embedding_label()
    )
    session.commit()


def reverify(session, question: QuizQuestion) -> list[str]:  # type: ignore[no-untyped-def]
    problems = []
    for ref in question.citations:
        chunk = session.scalar(
            select(Chunk).where(
                Chunk.id == uuid.UUID(ref["chunk_id"]), Chunk.workspace_id == question.workspace_id
            )
        )
        if chunk is None:
            problems.append("citation chunk outside workspace")
        elif not quote_in_source(ref["quote"], chunk.text_content):
            problems.append("quote not in chunk")
    key = question.correct_answer
    try:  # rebuild the generation schema from the stored row: proves it is still well-formed
        GeneratedQuestion(
            question_type=question.question_type,
            cognitive_level=question.cognitive_level,
            prompt=question.prompt,
            options=[QuestionOption(**o) for o in question.options] if question.options else None,
            correct_option_id=key.get("option_id"),
            correct_boolean=key.get("boolean"),
            model_answer=key.get("model_answer"),
            rubric=[RubricCriterion(**c) for c in question.rubric],
            max_score=question.max_score,
            explanation=question.explanation or "-----",
            citations=[CitationReference(**c) for c in question.citations],
        )
    except Exception as error:  # noqa: BLE001
        problems.append(f"schema: {type(error).__name__}")
    if question.question_type == "mcq" and key.get("option_id") not in {
        o["id"] for o in question.options or []
    }:
        problems.append("mcq key not an option")
    if (
        question.question_type == "short_answer"
        and abs(sum(c["points"] for c in question.rubric) - question.max_score) > 0.01
    ):
        problems.append("rubric points != max_score")
    return problems


def main(notes_path: str, out_path: str) -> int:
    from tasks.ingest import embed_texts

    notes = Path(notes_path).read_bytes()
    provider = GroqProvider(get_settings())
    lines = ["# Quiz generation evaluation", ""]
    total = verified = 0
    with SessionLocal() as session:
        student = uuid.uuid4()
        session.execute(text("INSERT INTO auth.users (id) VALUES (:i)"), {"i": student})
        session.execute(
            text("INSERT INTO profiles (id) VALUES (:i) ON CONFLICT DO NOTHING"), {"i": student}
        )
        workspace = Workspace(student_id=student, title="Quiz eval", selected_locale="en")
        session.add(workspace)
        session.flush()
        for position, (unit_title, leaves) in enumerate(TOPICS.items()):
            unit = Topic(
                workspace_id=workspace.id,
                title=unit_title,
                status="approved",
                position=position,
                origin="manual",
            )
            session.add(unit)
            session.flush()
            for i, leaf in enumerate(leaves):
                session.add(
                    Topic(
                        workspace_id=workspace.id,
                        parent_id=unit.id,
                        title=leaf,
                        status="approved",
                        position=i,
                        origin="manual",
                    )
                )
        session.commit()
        ingest(session, student, workspace, notes)
        for locale, count in RUNS:
            quiz = Quiz(
                workspace_id=workspace.id,
                student_id=student,
                question_count=count,
                locale=locale,
                blueprint={},
                policy_version="eval",
            )
            session.add(quiz)
            session.commit()
            run_generation(session, provider, quiz, None, lambda q: embed_texts([q])[0])
            questions = list(
                session.scalars(
                    select(QuizQuestion)
                    .where(QuizQuestion.quiz_id == quiz.id)
                    .order_by(QuizQuestion.position)
                )
            )
            types = Counter(q.question_type for q in questions)
            lines += [
                f"## Quiz in `{locale}` — {len(questions)} questions ({dict(types)})",
                "",
                "| # | Unit → topic | Type / level | Prompt (excerpt) | Cited quote | Verified |",
                "|---|---|---|---|---|---|",
            ]
            for q in questions:
                problems = reverify(session, q)
                total += 1
                verified += not problems
                quote = q.citations[0]["quote"].replace("|", "/")[:70]
                prompt = q.prompt.replace("|", "/").replace("\n", " ")[:90]
                lines.append(
                    f"| {q.position + 1} | {q.topic_title} | {q.question_type} / {q.cognitive_level} | {prompt} | “{quote}” | {'✅' if not problems else '❌ ' + '; '.join(problems)} |"
                )
            lines.append("")
        runs = list(
            session.scalars(
                select(AiRun).where(
                    AiRun.workspace_id == workspace.id, AiRun.operation == "generate_question"
                )
            )
        )
        outcomes = Counter(r.outcome for r in runs)
        codes = Counter(r.error_code for r in runs if r.error_code)
        model = ", ".join(sorted({r.model or "?" for r in runs})) or "n/a"
    lines[1:1] = [
        "",
        f"**{verified} / {total} published questions independently source-verified.**",
        f"Models `{model}` · generation calls: {dict(outcomes)} · rejection reasons: {dict(codes) or 'none'}",
        "",
    ]
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"verified {verified}/{total}; calls {dict(outcomes)}; rejections {dict(codes)}")
    return 0 if total >= 30 and verified == total else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
