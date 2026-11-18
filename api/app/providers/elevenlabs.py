"""ElevenLabs adapter: speech-to-text for spoken Explain questions, text-to-speech for validated
explanations. Explain only; English, Hindi, Punjabi, Telugu (Deccani voice stays disabled)."""

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger("gapfinder.elevenlabs")

# UI locale -> ISO-639-1 code ElevenLabs accepts. Deccani is deliberately absent (no supported voice language).
VOICE_LANGUAGE = {"en": "en", "hi-IN": "hi", "pa-IN": "pa", "te-IN": "te"}
MAX_TTS_CHARACTERS = 2500
MAX_AUDIO_BYTES = 2 * 1024 * 1024
AUDIO_MIME_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
}


class VoiceNotConfigured(RuntimeError):
    code = "VOICE_NOT_CONFIGURED"


class VoiceUnsupportedLanguage(RuntimeError):
    code = "VOICE_LANGUAGE_UNSUPPORTED"


class VoiceProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def voice_language(locale: str) -> str:
    language = VOICE_LANGUAGE.get(locale)
    if language is None:
        raise VoiceUnsupportedLanguage(locale)
    return language


Recorder = Callable[[str, str, str | None, int, dict[str, Any]], None]


def _noop(*_args: Any) -> None:
    return None


class ElevenLabsProvider:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        recorder: Recorder = _noop,
    ) -> None:
        if not settings.voice_configured:
            raise VoiceNotConfigured()
        self._settings = settings
        self._transport = transport
        self._record = recorder

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(
            base_url=self._settings.elevenlabs_base_url,
            timeout=timeout,
            transport=self._transport,
            headers={"xi-api-key": self._settings.elevenlabs_api_key or ""},
        )

    def transcribe(self, audio: bytes, mime_type: str, locale: str) -> str:
        language = voice_language(locale)
        if len(audio) > MAX_AUDIO_BYTES:
            raise VoiceProviderError("AUDIO_TOO_LARGE")
        started = time.perf_counter()
        with self._client(60) as client:
            response = client.post(
                "/v1/speech-to-text",
                data={
                    "model_id": self._settings.elevenlabs_stt_model_id,
                    "language_code": language,
                },
                files={"file": ("question", audio, mime_type)},
            )
        self._record(
            "speech_to_text",
            self._settings.elevenlabs_stt_model_id,
            _outcome(response),
            _ms(started),
            {"bytes": len(audio)},
        )
        _raise_for(response)
        text = str(response.json().get("text", "")).strip()
        if not text:
            raise VoiceProviderError("NO_SPEECH_DETECTED")
        return text[:1000]

    def speak(self, text: str, locale: str) -> bytes:
        language = voice_language(locale)
        started = time.perf_counter()
        with self._client(120) as client:
            response = client.post(
                f"/v1/text-to-speech/{self._settings.elevenlabs_voice_id}",
                params={"output_format": "mp3_44100_128"},
                json={
                    "text": text[:MAX_TTS_CHARACTERS],
                    "model_id": self._settings.elevenlabs_model_id,
                    "language_code": language,
                },
            )
        self._record(
            "text_to_speech",
            self._settings.elevenlabs_model_id,
            _outcome(response),
            _ms(started),
            {"characters": min(len(text), MAX_TTS_CHARACTERS)},
        )
        _raise_for(response)
        if not response.content:
            raise VoiceProviderError("EMPTY_AUDIO")
        return response.content


def _outcome(response: httpx.Response) -> str:
    return "accepted" if response.is_success else "provider_error"


def _raise_for(response: httpx.Response) -> None:
    if response.is_success:
        return
    code = {
        401: "VOICE_AUTH_FAILED",
        402: "VOICE_QUOTA_EXCEEDED",
        422: "VOICE_REQUEST_INVALID",
        429: "VOICE_RATE_LIMITED",
    }.get(response.status_code, "VOICE_PROVIDER_ERROR")
    if response.status_code == 402 and "paid_plan_required" in response.text:
        code = "VOICE_PLAN_REQUIRED"  # e.g. a Voice Library voice on the free plan: choose a premade voice
    logger.warning("ElevenLabs returned %s", response.status_code)
    raise VoiceProviderError(code)


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
