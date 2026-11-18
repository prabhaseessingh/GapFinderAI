"""Grounded Explain, refusal, voice/visual adapters (fakes), fair-use counters, isolation."""

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.fair_use import DAILY_LIMITS, FairUse, MemoryCounter, local_day_window
from app.db.models import Explanation, GeneratedAsset
from app.providers.elevenlabs import (
    ElevenLabsProvider,
    VoiceProviderError,
    VoiceUnsupportedLanguage,
)
from app.providers.groq import GroqOutputRejected
from app.providers.image_worker import ImageWorkerClient, VisualProviderError, build_request, sign
from app.schemas.explain import GroundedExplanation, VisualBrief, VisualElement, VisualRelation
from app.schemas.topics import CitationReference
from app.services import explain as explain_service
from app.services.explain import illustration_prompt, validate_brief, validate_explanation
from app.services.jobs import EXPLAIN, RENDER_AUDIO, RENDER_VISUAL
from app.services.retrieval import EvidenceBundle, EvidenceItem
from tests.factories import make_document, make_topic, make_workspace
from tests.helpers import FakeStorage, auth_headers, make_student

# ---- fair use (unit) ------------------------------------------------------------------------------


def test_daily_limits_match_the_architecture() -> None:
    assert DAILY_LIMITS == {"diagnostic": 10, "explain": 20, "voice": 10, "visual": 10}


@pytest.mark.parametrize("action", ["diagnostic", "explain", "voice", "visual"])
def test_counter_stops_exactly_at_the_limit(action: Any) -> None:
    fair = FairUse(MemoryCounter(), clock=lambda: datetime(2026, 11, 17, 12, tzinfo=UTC))
    student = uuid4()
    for _ in range(DAILY_LIMITS[action]):
        fair.consume(student, action, "Asia/Kolkata")
    with pytest.raises(AppError) as raised:
        fair.consume(student, action, "Asia/Kolkata")
    assert raised.value.status_code == 429 and raised.value.code == "RATE_LIMITED"
    fair.refund(student, action, "Asia/Kolkata")
    fair.consume(student, action, "Asia/Kolkata")  # a refund gives exactly one back


def test_reset_follows_the_students_local_midnight() -> None:
    # 20:00 UTC on 17 Nov is already 18 Nov in India: a new day there, not yet in London.
    now = datetime(2026, 11, 17, 20, 0, tzinfo=UTC)
    assert local_day_window("Asia/Kolkata", now)[0] == "2026-11-18"
    assert local_day_window("Europe/London", now)[0] == "2026-11-17"
    assert local_day_window("Not/AZone", now)[0] == "2026-11-17"  # unknown zone falls back to UTC
    counter = MemoryCounter()
    student = uuid4()
    FairUse(counter, clock=lambda: now).consume(student, "explain", "Asia/Kolkata")
    later = FairUse(
        counter, clock=lambda: datetime(2026, 11, 18, 19, 0, tzinfo=UTC)
    )  # 19 Nov 00:30 IST
    assert [u.used for u in later.usage(student, "Asia/Kolkata") if u.action == "explain"] == [0]


def test_counter_failure_fails_closed() -> None:
    class Broken(MemoryCounter):
        def incr_if_below(self, *_: Any) -> int | None:
            raise ConnectionError("redis down")

    with pytest.raises(AppError) as raised:
        FairUse(Broken()).consume(uuid4(), "voice", None)
    assert raised.value.status_code == 503


# ---- worker signing (unit; same vector as infra/cloudflare-image-worker/test) ----------------------


def test_hmac_vector_matches_the_worker_tests() -> None:
    body = b'{"explanation_id":"x","nonce":"y","prompt":"z"}'
    assert (
        sign("vector-secret", 1700000000, body)
        == "533f00956acde5e426f5de71c8a8f33d84cfab8d18e2f6ff603e8e0d8af36965"
    )


def test_worker_request_is_bounded_and_signed() -> None:
    with pytest.raises(VisualProviderError, match="PROMPT_INVALID"):
        build_request(str(uuid4()), "x" * 1001)
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["ts"] = request.headers["x-gf-timestamp"]
        seen["sig"] = request.headers["x-gf-signature"]
        return httpx.Response(200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"})

    settings = Settings(
        cloudflare_image_worker_url="https://w.example", cloudflare_image_worker_shared_secret="s3"
    )
    client = ImageWorkerClient(settings, transport=httpx.MockTransport(handler))
    assert client.render(str(uuid4()), "Clean diagram.") == b"\xff\xd8jpeg"
    expected = hmac.new(b"s3", f"{seen['ts']}.".encode() + seen["body"], hashlib.sha256).hexdigest()
    assert seen["sig"] == expected and set(json.loads(seen["body"])) == {
        "explanation_id",
        "nonce",
        "prompt",
    }


# ---- ElevenLabs adapter (unit, mocked transport) ------------------------------------------------


def _voice(handler: Any) -> ElevenLabsProvider:
    settings = Settings(elevenlabs_api_key="k", elevenlabs_voice_id="voice123")
    return ElevenLabsProvider(settings, transport=httpx.MockTransport(handler))


def test_transcribe_and_speak_use_configured_models_and_languages() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/speech-to-text":
            return httpx.Response(200, json={"text": " Explain photosynthesis "})
        return httpx.Response(200, content=b"ID3mp3")

    voice = _voice(handler)
    assert voice.transcribe(b"webm-bytes", "audio/webm", "te-IN") == "Explain photosynthesis"
    assert b'name="model_id"\r\n\r\nscribe_v2' in calls[0].content and b"te" in calls[0].content
    assert calls[0].headers["xi-api-key"] == "k"
    assert voice.speak("Hello", "hi-IN") == b"ID3mp3"
    body = json.loads(calls[1].content)
    assert calls[1].url.path == "/v1/text-to-speech/voice123"
    assert body == {"text": "Hello", "model_id": "eleven_v3", "language_code": "hi"}


def test_library_voice_on_free_plan_has_a_clear_code() -> None:
    body = {
        "detail": {
            "code": "paid_plan_required",
            "message": "Free users cannot use library voices via the API.",
        }
    }
    voice = _voice(lambda _r: httpx.Response(402, json=body))
    with pytest.raises(VoiceProviderError, match="VOICE_PLAN_REQUIRED"):
        voice.speak("x", "en")


def test_deccani_voice_is_refused_and_errors_are_mapped() -> None:
    voice = _voice(lambda _r: httpx.Response(402, json={}))
    with pytest.raises(VoiceUnsupportedLanguage):
        voice.speak("x", "deccani-Latn")
    with pytest.raises(VoiceProviderError, match="VOICE_QUOTA_EXCEEDED"):
        voice.speak("x", "en")
    with pytest.raises(VoiceProviderError, match="AUDIO_TOO_LARGE"):
        voice.transcribe(b"x" * (2 * 1024 * 1024 + 1), "audio/webm", "en")


# ---- validators (unit) ---------------------------------------------------------------------------

CHUNK = uuid4()
SOURCE = "Photosynthesis uses carbon dioxide, water and sunlight; chlorophyll absorbs light and the plant releases oxygen."
BUNDLE = EvidenceBundle(
    "q",
    ("notes",),
    [EvidenceItem(CHUNK, uuid4(), 1, "notes.txt", "notes", 1, 1, [], SOURCE, "en", 1.0)],
)


def _explanation(**overrides: Any) -> GroundedExplanation:
    base: dict[str, Any] = {
        "answer": "Plants make food using light.",
        "insufficient_workspace_evidence": False,
        "suggested_next_action": "none",
        "citations": [CitationReference(chunk_id=CHUNK, quote="chlorophyll absorbs light")],
    }
    return GroundedExplanation(**(base | overrides))


def test_explanation_gate() -> None:
    validate_explanation(_explanation(), BUNDLE)
    validate_explanation(
        _explanation(insufficient_workspace_evidence=True, citations=[], answer=""), BUNDLE
    )
    for overrides, code in [
        ({"citations": []}, "EXPLAIN_CITATION_REQUIRED"),
        (
            {"citations": [CitationReference(chunk_id=uuid4(), quote="chlorophyll absorbs light")]},
            "CITATION_NOT_IN_EVIDENCE",
        ),
        (
            {"citations": [CitationReference(chunk_id=CHUNK, quote="plants are made of cheese")]},
            "CITATION_QUOTE_NOT_IN_SOURCE",
        ),
        ({"answer": "  "}, "EMPTY_ANSWER"),
    ]:
        with pytest.raises(ValueError, match=code):
            validate_explanation(_explanation(**overrides), BUNDLE)


def _brief(**overrides: Any) -> VisualBrief:
    base: dict[str, Any] = {
        "visualizable": True,
        "kind": "process",
        "title": "Photosynthesis",
        "elements": [
            VisualElement(
                label="sunlight", citation=CitationReference(chunk_id=CHUNK, quote="sunlight")
            ),
            VisualElement(
                label="oxygen", citation=CitationReference(chunk_id=CHUNK, quote="releases oxygen")
            ),
        ],
        "relations": [VisualRelation(source="sunlight", relation="produces", target="oxygen")],
    }
    return VisualBrief(**(base | overrides))


def test_visual_brief_gate_and_prompt_template() -> None:
    sources = {CHUNK: SOURCE}
    validate_brief(_brief(), sources)
    with pytest.raises(ValueError, match="BRIEF_TOO_FEW_ELEMENTS"):
        validate_brief(_brief(elements=_brief().elements[:1], relations=[]), sources)
    with pytest.raises(ValueError, match="CITATION_QUOTE_NOT_IN_SOURCE"):
        validate_brief(
            _brief(
                elements=[
                    *_brief().elements[:1],
                    VisualElement(
                        label="dragon", citation=CitationReference(chunk_id=CHUNK, quote="a dragon")
                    ),
                ],
                relations=[],
            ),
            sources,
        )
    with pytest.raises(ValueError, match="RELATION_UNKNOWN_ELEMENT"):
        validate_brief(
            _brief(relations=[VisualRelation(source="sunlight", relation="feeds", target="moon")]),
            sources,
        )
    prompt = illustration_prompt(_brief())
    assert prompt.startswith(
        "A wordless picture-book scene in flat colours showing sunlight and oxygen: sunlight produces oxygen."
    )
    assert "No text, labels, letters or numbers." in prompt and "diagram" not in prompt
    assert len(prompt) <= 1000


# ---- integration ---------------------------------------------------------------------------------

NOTES = [
    SOURCE,
    "Ohm's law states that the current through a conductor is proportional to the potential difference across it.",
]


class FakeGroq:
    """Obeys the same validate gate as the real provider; `general` simulates an ungrounded answer."""

    def __init__(self, mode: str = "grounded") -> None:
        self.mode, self.calls = mode, 0

    def model_for(self, _tier: str) -> str:
        return "fake"

    def structured(
        self, _ctx: Any, *, output: Any, system: str, user: str, validate: Any, **_: Any
    ) -> Any:
        self.calls += 1
        assert "untrusted" in system
        chunk = re.search(r'chunk_id="([^"]+)"', user).group(1)  # type: ignore[union-attr]
        if output is VisualBrief:
            result: Any = VisualBrief(
                visualizable=self.mode != "abstract",
                kind="process" if self.mode != "abstract" else "none",
                title="Photosynthesis",
                relations=[],
                elements=[]
                if self.mode == "abstract"
                else [
                    VisualElement(
                        label="sunlight",
                        citation=CitationReference(chunk_id=UUID(chunk), quote="sunlight"),
                    ),
                    VisualElement(
                        label="oxygen",
                        citation=CitationReference(chunk_id=UUID(chunk), quote="releases oxygen"),
                    ),
                ],
            )
        elif self.mode == "insufficient":
            result = GroundedExplanation(
                answer="",
                citations=[],
                insufficient_workspace_evidence=True,
                suggested_next_action="upload_material",
            )
        elif self.mode == "general":
            result = GroundedExplanation(
                answer="Photosynthesis was discovered by Jan Ingenhousz in 1779.",
                citations=[],
                insufficient_workspace_evidence=False,
                suggested_next_action="none",
            )
        else:
            result = GroundedExplanation(
                answer="Plants use sunlight; chlorophyll absorbs light and oxygen is released.",
                citations=[
                    CitationReference(chunk_id=UUID(chunk), quote="chlorophyll absorbs light")
                ],
                insufficient_workspace_evidence=False,
                suggested_next_action="none",
            )
        try:
            validate(result)
        except ValueError as error:
            raise GroqOutputRejected(str(error)) from error
        return result


class FakeVoice:
    def __init__(self) -> None:
        self.spoken: list[tuple[str, str]] = []

    def speak(self, text_: str, locale: str) -> bytes:
        self.spoken.append((text_, locale))
        return b"ID3audio"


class FakeImage:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.prompts = fail, []

    def render(self, _explanation_id: str, prompt: str) -> bytes:
        self.prompts.append(prompt)
        if self.fail:
            raise VisualProviderError("VISUAL_PROVIDER_ERROR")
        return b"\xff\xd8jpeg"


@pytest.fixture()
def world(db: Session) -> dict[str, Any]:
    student = make_student(db)
    ws = make_workspace(db, student)
    make_document(db, ws, "notes", chunks=NOTES, seed=40)
    topic = make_topic(db, ws, "Photosynthesis", status="approved")
    return {"student": student, "ws": ws, "topic": topic, "headers": auth_headers(student)}


def _settings(**values: Any) -> Settings:
    return get_settings().model_copy(update=values)


@pytest.fixture()
def with_settings(client: Any) -> Any:
    from app.main import app

    def apply(**values: Any) -> None:
        app.dependency_overrides[get_settings] = lambda: _settings(**values)

    return apply


def _ask(
    client: Any,
    world: dict[str, Any],
    question: str = "How do plants make food from sunlight?",
    locale: str = "en",
) -> dict[str, Any]:
    response = client.post(
        "/explanations",
        headers=world["headers"],
        json={
            "workspace_id": str(world["ws"].id),
            "question": question,
            "locale": locale,
            "topic_id": str(world["topic"].id),
            "origin": "topic",
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def _answer(db: Session, explanation_id: str, groq: Any) -> str:
    # The fixture's first notes chunk carries unit_vector(40); a real embedding of a related question lands near it.
    vector = [0.0] * 384
    vector[40] = 1.0
    return explain_service.run_explanation(db, groq, UUID(explanation_id), lambda _q: vector)


@pytest.mark.integration
def test_grounded_explanation_with_citations(
    client: Any, db: Session, world: dict[str, Any], queue: list[Any]
) -> None:
    created = _ask(client, world)
    assert created["state"] == "queued" and (EXPLAIN, [created["id"]], created["id"]) in queue
    assert _answer(db, created["id"], FakeGroq()) == "answered"
    view = client.get(f"/explanations/{created['id']}", headers=world["headers"]).json()
    assert (
        view["state"] == "answered"
        and view["citations"][0]["original_quote"] == "chlorophyll absorbs light"
    )
    assert view["citations"][0]["document_name"].startswith("notes")
    listed = client.get(
        f"/explanations/workspace/{world['ws'].id}", headers=world["headers"]
    ).json()
    assert [e["id"] for e in listed] == [created["id"]]
    assert _answer(db, created["id"], FakeGroq()) == "answered"  # idempotent redelivery


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["insufficient", "general"])
def test_unsupported_questions_get_no_general_knowledge_answer(
    client: Any, db: Session, world: dict[str, Any], mode: str
) -> None:
    created = _ask(client, world, "Who discovered photosynthesis and in what year?")
    state = _answer(db, created["id"], FakeGroq(mode))
    row = db.get(Explanation, UUID(created["id"]))
    assert row is not None
    if mode == "insufficient":
        assert (
            state == "insufficient" and row.answer is None and row.next_action == "upload_material"
        )
    else:  # an uncited answer is rejected by the gate and never stored
        assert (
            state == "failed"
            and row.answer is None
            and row.failure_code.startswith("EXPLAIN_REJECTED")
        )  # type: ignore[union-attr]


@pytest.mark.integration
def test_no_evidence_means_refusal_without_a_model_call(client: Any, db: Session) -> None:
    student = make_student(db)
    ws = make_workspace(db, student)
    make_topic(db, ws, "Cells", status="approved")
    headers = auth_headers(student)
    created = client.post(
        "/explanations",
        headers=headers,
        json={"workspace_id": str(ws.id), "question": "Explain mitosis", "locale": "hi-IN"},
    ).json()
    groq = FakeGroq()
    assert _answer(db, created["id"], groq) == "insufficient" and groq.calls == 0


@pytest.mark.integration
def test_explain_limit_and_limits_endpoint(
    client: Any, world: dict[str, Any], fair_use: FairUse
) -> None:
    for _ in range(20):
        _ask(client, world)
    over = client.post(
        "/explanations",
        headers=world["headers"],
        json={
            "workspace_id": str(world["ws"].id),
            "question": "One more question please",
            "locale": "en",
        },
    )
    assert over.status_code == 429 and over.json()["error"]["code"] == "RATE_LIMITED"
    limits = {
        a["action"]: a for a in client.get("/limits", headers=world["headers"]).json()["actions"]
    }
    assert (
        limits["explain"]["used"] == 20
        and limits["explain"]["limit"] == 20
        and limits["voice"]["used"] == 0
    )
    assert (
        client.patch(
            "/profile", headers=world["headers"], json={"timezone": "Asia/Kolkata"}
        ).json()["timezone"]
        == "Asia/Kolkata"
    )
    assert (
        client.patch(
            "/profile", headers=world["headers"], json={"timezone": "Mars/Base"}
        ).status_code
        == 422
    )


@pytest.mark.integration
def test_voice_not_configured_and_deccani_are_honest(
    client: Any, db: Session, world: dict[str, Any], with_settings: Any
) -> None:
    with_settings(elevenlabs_api_key=None, elevenlabs_voice_id=None)
    created = _ask(client, world)
    _answer(db, created["id"], FakeGroq())
    view = client.get(f"/explanations/{created['id']}", headers=world["headers"]).json()
    assert view["voice_available"] is False and view["voice_reason"] == "not_configured"
    assert (
        client.post(f"/explanations/{created['id']}/audio", headers=world["headers"]).status_code
        == 409
    )
    audio = base64.b64encode(b"x" * 64).decode()
    body = {
        "workspace_id": str(world["ws"].id),
        "locale": "en",
        "mime_type": "audio/webm",
        "audio_base64": audio,
    }
    assert client.post("/voice/transcribe", headers=world["headers"], json=body).status_code == 409
    with_settings(elevenlabs_api_key="k", elevenlabs_voice_id="v")
    dcc = _ask(client, world, locale="deccani-Latn")
    _answer(db, dcc["id"], FakeGroq())
    view = client.get(f"/explanations/{dcc['id']}", headers=world["headers"]).json()
    assert view["voice_reason"] == "language_unsupported"
    assert (
        client.post(f"/explanations/{dcc['id']}/audio", headers=world["headers"]).status_code == 409
    )
    assert (
        client.post(
            "/voice/transcribe", headers=world["headers"], json=body | {"locale": "deccani-Latn"}
        ).status_code
        == 409
    )


@pytest.mark.integration
def test_audio_is_cached_counted_once_and_private(
    client: Any,
    db: Session,
    world: dict[str, Any],
    queue: list[Any],
    with_settings: Any,
    storage: FakeStorage,
) -> None:
    with_settings(elevenlabs_api_key="k", elevenlabs_voice_id="v")
    created = _ask(client, world)
    _answer(db, created["id"], FakeGroq())
    first = client.post(f"/explanations/{created['id']}/audio", headers=world["headers"]).json()
    again = client.post(f"/explanations/{created['id']}/audio", headers=world["headers"]).json()
    assert first["id"] == again["id"] and first["state"] == "queued"
    assert [q for q in queue if q[0] == RENDER_AUDIO] == [
        (RENDER_AUDIO, [first["id"]], first["id"])
    ]
    voice = FakeVoice()
    assert explain_service.render_audio(db, voice, storage, UUID(first["id"])) == "ready"  # type: ignore[arg-type]
    assert voice.spoken[0][1] == "en"
    ready = client.get(f"/assets/{first['id']}", headers=world["headers"]).json()
    assert ready["state"] == "ready" and ready["url"]
    limits = {
        a["action"]: a["used"]
        for a in client.get("/limits", headers=world["headers"]).json()["actions"]
    }
    assert limits["voice"] == 1
    stranger = auth_headers(
        make_student(db)
    )  # guessed ids cannot create or play another student's assets
    assert client.get(f"/assets/{first['id']}", headers=stranger).status_code == 404
    assert client.post(f"/explanations/{created['id']}/audio", headers=stranger).status_code == 404
    assert client.post(f"/explanations/{created['id']}/visual", headers=stranger).status_code == 404
    assert client.get(f"/explanations/{created['id']}", headers=stranger).status_code == 404
    body = {
        "workspace_id": str(world["ws"].id),
        "locale": "en",
        "mime_type": "audio/webm",
        "audio_base64": base64.b64encode(b"x" * 64).decode(),
    }
    assert client.post("/voice/transcribe", headers=stranger, json=body).status_code == 404


@pytest.mark.integration
def test_cited_source_figure_is_preferred_over_a_generated_image(
    client: Any, db: Session, world: dict[str, Any], with_settings: Any, fair_use: FairUse
) -> None:
    with_settings(
        cloudflare_image_worker_url="https://w.example", cloudflare_image_worker_shared_secret="s"
    )
    db.execute(
        text("UPDATE documents SET mime_type = 'application/pdf' WHERE workspace_id = :w"),
        {"w": world["ws"].id},
    )
    db.execute(
        text(
            "UPDATE chunks SET text_content = text_content || ' See Fig. 2 for the leaf.' WHERE workspace_id = :w"
        ),
        {"w": world["ws"].id},
    )
    db.commit()
    created = _ask(client, world)
    _answer(db, created["id"], FakeGroq())
    asset = client.post(f"/explanations/{created['id']}/visual", headers=world["headers"]).json()
    assert (
        asset["kind"] == "source_figure"
        and asset["state"] == "ready"
        and asset["meta"]["page"] == 1
    )
    url = client.get(f"/assets/{asset['id']}", headers=world["headers"]).json()["url"]
    assert url and url.endswith("#page=1")
    limits = {
        a["action"]: a["used"]
        for a in client.get("/limits", headers=world["headers"]).json()["actions"]
    }
    assert limits["visual"] == 0  # showing the original source costs nothing


@pytest.mark.integration
def test_generated_illustration_is_labelled_never_a_citation_and_failure_keeps_answer(
    client: Any,
    db: Session,
    world: dict[str, Any],
    queue: list[Any],
    with_settings: Any,
    storage: FakeStorage,
) -> None:
    with_settings(
        cloudflare_image_worker_url="https://w.example", cloudflare_image_worker_shared_secret="s"
    )
    created = _ask(client, world)
    _answer(db, created["id"], FakeGroq())
    before = client.get(f"/explanations/{created['id']}", headers=world["headers"]).json()
    asset = client.post(f"/explanations/{created['id']}/visual", headers=world["headers"]).json()
    assert asset["kind"] == "illustration" and (RENDER_VISUAL, [asset["id"]], asset["id"]) in queue
    image = FakeImage(fail=True)
    assert (
        explain_service.render_visual(db, FakeGroq(), image, storage, UUID(asset["id"])) == "failed"
    )  # type: ignore[arg-type]
    after = client.get(f"/explanations/{created['id']}", headers=world["headers"]).json()
    assert (
        after["answer"] == before["answer"] and after["citations"] == before["citations"]
    )  # answer intact
    retry = client.post(f"/explanations/{created['id']}/visual", headers=world["headers"]).json()
    assert retry["id"] == asset["id"] and retry["state"] == "queued"
    image = FakeImage()
    assert (
        explain_service.render_visual(db, FakeGroq(), image, storage, UUID(asset["id"])) == "ready"
    )  # type: ignore[arg-type]
    assert "sunlight" in image.prompts[0] and "No text, labels" in image.prompts[0]
    final = client.get(f"/explanations/{created['id']}", headers=world["headers"]).json()
    assert final["citations"] == before["citations"]  # the image never becomes a citation
    shown = next(a for a in final["assets"] if a["kind"] == "illustration")
    assert shown["state"] == "ready" and shown["meta"]["ai_generated"] is True


@pytest.mark.integration
def test_abstract_content_is_not_illustrated(
    client: Any, db: Session, world: dict[str, Any], with_settings: Any, storage: FakeStorage
) -> None:
    with_settings(
        cloudflare_image_worker_url="https://w.example", cloudflare_image_worker_shared_secret="s"
    )
    created = _ask(client, world)
    _answer(db, created["id"], FakeGroq())
    asset = client.post(f"/explanations/{created['id']}/visual", headers=world["headers"]).json()
    image = FakeImage()
    assert (
        explain_service.render_visual(db, FakeGroq("abstract"), image, storage, UUID(asset["id"]))
        == "not_eligible"
    )  # type: ignore[arg-type]
    assert image.prompts == []


@pytest.mark.integration
def test_workspace_deletion_removes_generated_assets(
    client: Any, db: Session, world: dict[str, Any], with_settings: Any, storage: FakeStorage
) -> None:
    with_settings(elevenlabs_api_key="k", elevenlabs_voice_id="v")
    created = _ask(client, world)
    _answer(db, created["id"], FakeGroq())
    asset = client.post(f"/explanations/{created['id']}/audio", headers=world["headers"]).json()
    explain_service.render_audio(db, FakeVoice(), storage, UUID(asset["id"]))  # type: ignore[arg-type]
    path = db.scalar(
        select(GeneratedAsset.storage_path).where(GeneratedAsset.id == UUID(asset["id"]))
    )
    assert path and path.startswith(f"workspaces/{world['ws'].id}/assets/")
    assert (
        client.delete(f"/workspaces/{world['ws'].id}", headers=world["headers"]).status_code == 204
    )
    assert path in storage.deleted
    assert db.scalar(select(GeneratedAsset).where(GeneratedAsset.id == UUID(asset["id"]))) is None


@pytest.mark.integration
def test_diagnostic_generation_counts_toward_the_daily_limit(
    client: Any, db: Session, world: dict[str, Any], fair_use: FairUse
) -> None:
    body = {"workspace_id": str(world["ws"].id), "question_count": 5}
    for _ in range(10):
        assert client.post("/quizzes", json=body, headers=world["headers"]).status_code == 202
    over = client.post("/quizzes", json=body, headers=world["headers"])
    assert over.status_code == 429
