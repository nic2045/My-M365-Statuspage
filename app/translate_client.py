import logging

import httpx

logger = logging.getLogger(__name__)

_DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"
_DEEPL_PRO_URL = "https://api.deepl.com/v2/translate"

# DeepL wants ISO 639-1 target codes, not the locale tags the rest of the
# app uses. Source is always English (Microsoft's service-health text), so
# there's nothing to translate when the target is English too.
_DEEPL_TARGET_MAP: dict[str, str] = {
    "de": "DE",
}

# In-process cache: Microsoft repeats the same English title/description
# unchanged across poll cycles, so without this every poll would re-translate
# identical text through a metered API. Cleared on restart - that just costs
# one extra call per string, not a correctness issue.
_cache: dict[tuple[str, str, str], str] = {}


def _deepl_url(api_key: str, override: str) -> str:
    if override:
        return override
    return _DEEPL_FREE_URL if api_key.endswith(":fx") else _DEEPL_PRO_URL


async def translate_text(text: str, target_lang: str, *, tag_handling: str = "") -> str:
    """Translate English `text` into `target_lang` via DeepL.

    Never raises: returns `text` unchanged if DeepL isn't configured, the
    target language has no mapping, the text is empty, or the API call
    fails. Translation is a display nicety, never a reason to lose or block
    on Microsoft's original incident data.
    """
    from app.config import settings  # noqa: PLC0415

    if not text or not settings.DEEPL_API_KEY:
        return text
    deepl_lang = _DEEPL_TARGET_MAP.get(target_lang)
    if not deepl_lang:
        return text

    cache_key = (text, deepl_lang, tag_handling)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    payload: dict[str, str] = {
        "text": text,
        "source_lang": "EN",
        "target_lang": deepl_lang,
    }
    if tag_handling:
        payload["tag_handling"] = tag_handling

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _deepl_url(settings.DEEPL_API_KEY, settings.DEEPL_API_URL),
                headers={"Authorization": f"DeepL-Auth-Key {settings.DEEPL_API_KEY}"},
                data=payload,
            )
            resp.raise_for_status()
            translated = resp.json()["translations"][0]["text"]
    except Exception:
        logger.exception("DeepL translation failed, keeping original text")
        return text

    _cache[cache_key] = translated
    return translated
