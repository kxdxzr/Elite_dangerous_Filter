"""Presentation-only localization; query values and game identifiers stay canonical."""
from importlib import import_module
import re

from translations.en import CATALOG, FRAGMENTS  # Compatibility for existing callers/tests.


SOURCE_LANGUAGE = 'zh'
FALLBACK_LANGUAGE = 'en'
# Native display names are stable, not translated. Packs are bundled, never downloaded.
LANGUAGES = {'zh': '中文', 'en': 'English'}


def normalize_language(language):
    return language if language in LANGUAGES else SOURCE_LANGUAGE


def language_code(display_name):
    return next((code for code, label in LANGUAGES.items() if label == display_name), SOURCE_LANGUAGE)


def _pack(language):
    if language == SOURCE_LANGUAGE:
        return {}, {}
    module = import_module(f'translations.{language}')
    return module.CATALOG, getattr(module, 'FRAGMENTS', {})


def _english(text):
    if text in CATALOG:
        return CATALOG[text]
    if not re.search(r'[\u3400-\u9fff]', text):
        return text
    field = re.fullmatch(r'.*[\u3400-\u9fff].* \(([a-z_]+)\)', text)
    if field:
        key = field.group(1)
        return f"{key.replace('_', ' ').title()} ({key})"
    text = re.sub(r'近(\d+)天', r'Last \1 days', text)
    text = re.sub(r'数据(\d+)天内', r'data within \1 days', text)
    text = re.sub(r'(\d+)\s*个(?=[；。])', r'\1', text)
    text = re.sub(r'等(\d+)项', r' and others (\1 items)', text)
    text = re.sub(r'距(?=[^\n]*ly范围[内外])', 'Distance to ', text)
    text = re.sub(r'=否(?=由本地过滤)', '=False', text)
    catalog = dict(CATALOG, **FRAGMENTS)
    for source in sorted(catalog, key=len, reverse=True):
        if len(source) > 1:
            text = text.replace(source, catalog[source])
    text = re.sub(r'第(\d+)条条件', r'Condition \1', text)
    text = re.sub(r'(\d+)\s*条', r'\1 rows', text)
    text = re.sub(r'(\d+)页', r'\1', text)
    text = re.sub(r'([0-8A-I])级', r'\1', text)
    for source, target in [('；', '; '), ('，', ', '), ('：', ': '), ('。', '. '), ('、', ', ')]:
        text = text.replace(source, target)
    return text


def translate(text, language=SOURCE_LANGUAGE):
    if not isinstance(text, str):
        return text
    language = normalize_language(language)
    if language == SOURCE_LANGUAGE:
        return text
    if language == FALLBACK_LANGUAGE:
        return _english(text)
    catalog, _ = _pack(language)
    # Whole templates are translated before formatting. Missing entries use English;
    # do not splice unrelated-language fragments into an English fallback sentence.
    return catalog.get(text) or _english(text)


def format_text(text, language=SOURCE_LANGUAGE, **values):
    """Translate a complete template, then substitute unchanged runtime values."""
    return translate(text, language).format(**values)


def message(key, language=SOURCE_LANGUAGE, **values):
    """Format a stable message ID; missing target templates fall back to English."""
    language = normalize_language(language)
    source = import_module(f'translations.{SOURCE_LANGUAGE}').MESSAGES
    fallback = import_module(f'translations.{FALLBACK_LANGUAGE}').MESSAGES
    target = getattr(import_module(f'translations.{language}'), 'MESSAGES', {})
    template = target.get(key) or fallback.get(key) or source.get(key)
    if template is None:
        raise KeyError(f'Unknown translation message: {key}')
    return template.format(**values)


def export_text(value, language):
    """Apply a pack's export policy, independently of the CSV implementation."""
    language = normalize_language(language)
    if getattr(import_module(f'translations.{language}'), 'EXPORT_ESCAPE_CJK', False):
        return re.sub(r'[\u3400-\u9fff]', lambda match: '\\u%04x' % ord(match[0]), value)
    return value


def missing_translations(language):
    """Return canonical English-pack keys missing from a registered target pack."""
    if language not in LANGUAGES:
        raise ValueError('Unsupported language')
    if language == SOURCE_LANGUAGE:
        return []
    catalog, _ = _pack(language)
    source_messages = import_module(f'translations.{SOURCE_LANGUAGE}').MESSAGES
    target_messages = getattr(import_module(f'translations.{language}'), 'MESSAGES', {})
    return sorted(set(CATALOG) - set(catalog)) + [
        f'@{key}' for key in sorted(set(source_messages) - set(target_messages))]


class Localizer:
    def __init__(self, root, language=SOURCE_LANGUAGE):
        self.root, self.language = root, normalize_language(language)
        self.callbacks = set()
        root._localizer = self

    def tr(self, text):
        return translate(text, self.language)

    def format(self, text, **values):
        return format_text(text, self.language, **values)

    def message(self, key, **values):
        return message(key, self.language, **values)

    def register(self, callback):
        self.callbacks.add(callback)
        callback()

    def set_language(self, language):
        if language not in LANGUAGES:
            raise ValueError('Unsupported language')
        self.language = language
        for callback in tuple(self.callbacks):
            callback()
