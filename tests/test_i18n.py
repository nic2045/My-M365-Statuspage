"""Tests for i18n completeness and label availability."""
import re
import pathlib
from app.i18n import LABELS_DE, LABELS_EN, LABELS_BY_LANG


def test_all_template_keys_present():
    """All L[...] references in templates must have an entry in LABELS_DE or LABELS_EN."""
    template_dir = pathlib.Path("templates")
    used_keys = set()

    # Regex to find L["key"] or L['key'] patterns
    pattern = r"L\[['\"]([^'\"]+)['\"]\]"

    for template_file in template_dir.rglob("*.html"):
        content = template_file.read_text(encoding="utf-8")
        for match in re.finditer(pattern, content):
            key = match.group(1)
            used_keys.add(key)

    # Check that all used keys exist in at least one language dictionary
    all_keys = set(LABELS_DE.keys()) | set(LABELS_EN.keys())
    missing = used_keys - all_keys
    assert not missing, f"Missing i18n keys: {missing}"


def test_all_labels_de_have_corresponding_en():
    """Each German label should have an English translation."""
    missing_en = {}

    for key in LABELS_DE.keys():
        if key not in LABELS_EN:
            missing_en[key] = f"Missing English translation"

    assert not missing_en, f"Missing English translations: {missing_en}"


def test_all_label_values_non_empty():
    """All label values should be non-empty strings."""
    empty_labels_de = [k for k, v in LABELS_DE.items() if not v or not str(v).strip()]
    empty_labels_en = [k for k, v in LABELS_EN.items() if not v or not str(v).strip()]

    empty_labels = {
        "de": empty_labels_de,
        "en": empty_labels_en,
    }

    errors = {lang: keys for lang, keys in empty_labels.items() if keys}
    assert not errors, f"Empty label values found: {errors}"


def test_labels_by_lang_structure():
    """LABELS_BY_LANG should have correct structure."""
    assert "de" in LABELS_BY_LANG, "Missing 'de' in LABELS_BY_LANG"
    assert "en" in LABELS_BY_LANG, "Missing 'en' in LABELS_BY_LANG"
    assert LABELS_BY_LANG["de"] is LABELS_DE
    assert LABELS_BY_LANG["en"] is LABELS_EN
