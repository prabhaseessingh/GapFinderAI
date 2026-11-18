"""Citation translation.

Groq receives only the cited original quote plus the target locale. Results are cached per
(chunk, quote hash, locale). The original quote, page and language are never altered; when no
translation is available the UI shows the original only.
"""

import hashlib
import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import CitationTranslation
from app.providers.groq import UNTRUSTED_SOURCE_RULE, AiCallContext, GroqProvider, source_block
from app.schemas.topics import CitationOut, QuoteTranslations

logger = logging.getLogger("gapfinder.translation")
TRANSLATION_PROMPT_VERSION = "translate-quote-v1"

LOCALE_LANGUAGE = {
    "en": "en",
    "hi-IN": "hi",
    "pa-IN": "pa",
    "te-IN": "te",
    "deccani-Latn": "deccani",
}
LOCALE_DESCRIPTION = {
    "en": "English",
    "hi-IN": "Hindi in Devanagari script",
    "pa-IN": "Punjabi in Gurmukhi script",
    "te-IN": "Telugu in Telugu script",
    "deccani-Latn": "Hyderabadi Deccani (Dakhini) written in Latin script",
}


def needs_translation(source_language: str, locale: str) -> bool:
    if source_language in ("und", ""):
        return False
    return LOCALE_LANGUAGE.get(locale, "en") != source_language


def quote_hash(quote: str) -> str:
    return hashlib.sha256(quote.encode("utf-8")).hexdigest()


def translate_citations(
    session: Session,
    provider: GroqProvider | None,
    student_id: UUID,
    workspace_id: UUID,
    citations: Sequence[CitationOut],
    locale: str,
) -> list[CitationOut]:
    targets = [c for c in citations if needs_translation(c.source_language, locale)]
    if not targets:
        return list(citations)
    keys = {(c.chunk_id, quote_hash(c.original_quote)) for c in targets}
    cached = {
        (row.chunk_id, row.quote_hash): row.translated_text
        for row in session.scalars(
            select(CitationTranslation).where(
                CitationTranslation.workspace_id == workspace_id,
                CitationTranslation.target_locale == locale,
                CitationTranslation.chunk_id.in_([k[0] for k in keys]),
            )
        )
    }
    missing = [c for c in targets if (c.chunk_id, quote_hash(c.original_quote)) not in cached]
    if missing and provider is not None:
        ids = {str(index): c for index, c in enumerate(missing)}

        def validate(result: QuoteTranslations) -> None:
            if {t.id for t in result.translations} != set(ids):
                raise ValueError("TRANSLATION_IDS_MISMATCH")

        try:
            result = provider.structured(
                AiCallContext(
                    "translate_quote",
                    TRANSLATION_PROMPT_VERSION,
                    student_id,
                    workspace_id,
                    [c.chunk_id for c in missing],
                ),
                output=QuoteTranslations,
                system=f"You are a faithful translator. {UNTRUSTED_SOURCE_RULE}",
                user=(
                    f"Translate each source into {LOCALE_DESCRIPTION.get(locale, 'English')}. "
                    "Translate meaning faithfully; do not summarise, explain, add or omit content. "
                    "Keep formulas, numbers and proper nouns unchanged. Return one translation per id.\n\n"
                    + source_block(
                        [{"id": key, "text": c.original_quote} for key, c in ids.items()]
                    )
                ),
                validate=validate,
            )
            model = provider.model_for("fast")
            for item in result.translations:
                citation = ids[item.id]
                digest = quote_hash(citation.original_quote)
                cached[(citation.chunk_id, digest)] = item.translation
                session.execute(
                    insert(CitationTranslation)
                    .values(
                        workspace_id=workspace_id,
                        chunk_id=citation.chunk_id,
                        quote_hash=digest,
                        target_locale=locale,
                        translated_text=item.translation,
                        model=model,
                        prompt_version=TRANSLATION_PROMPT_VERSION,
                    )
                    .on_conflict_do_nothing()
                )
            session.commit()
        except Exception:
            session.rollback()
            logger.warning("Citation translation unavailable", exc_info=True)
    out: list[CitationOut] = []
    for citation in citations:
        translated = cached.get((citation.chunk_id, quote_hash(citation.original_quote)))
        if translated and needs_translation(citation.source_language, locale):
            citation = citation.model_copy(
                update={"translated_quote": translated, "translation_locale": locale}
            )
        out.append(citation)
    return out
