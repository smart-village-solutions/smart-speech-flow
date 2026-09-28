# Conversation-language display fallback implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve Studio display fields for any selected conversation language using reviewed text first and a safe, field-level translation fallback.

**Architecture:** An internal Gateway module accepts a validated `RuntimeConfiguration`, conversation code, and existing `SpeechServices` interface. It selects one source per field, translates plain text or HTML text nodes, and returns safe field values without exposing a route or changing session language.

**Tech Stack:** Python 3.12, Pydantic V2, pytest, existing Gateway translation service, `nh3` HTML sanitizer.

**Spec:** `docs/superpowers/specs/2026-09-28-conversation-language-display-fallback-design.md`; OpenSpec change `openspec/changes/add-conversation-language-display-fallback/`.

## Global Constraints

- Await explicit review and approval of the OpenSpec proposal before implementing code, per `openspec/AGENTS.md`.
- Keep `/api/languages/supported` and the existing picker unchanged; do not connect UI screens or add an API route.
- Do not change Studio's V1 schema, code, or documentation.
- Resolve only explicitly registered fields; leave unknown optional Studio fields untouched.
- Treat Studio outage and invalid runtime configuration as outside this change.
- All new or modified project documentation is in English.

## File map

- `services/api_gateway/display_text_fallback.py` (new): field definitions, locale/source selection, translation adapter, safe HTML handling, internal result.
- `tests/test_display_text_fallback.py` (new): per-field branch tests, locale selection, translation behavior, HTML safety, storage-disabled behavior, plain-text extension.
- `services/api_gateway/requirements.in` and `requirements.txt`: add and lock `nh3` for safe HTML fragments.
- `docs/architecture/SYSTEM_ARCHITECTURE.md`: document the SSF-only display fallback and its contract boundary.
- OpenSpec `proposal.md`, `tasks.md`, and new capability `spec.md`: already drafted; validate, review, and update task checkboxes after implementation.

---

### Task 1: Field selection and locale mapping

**Files:** Create `services/api_gateway/display_text_fallback.py`; create `tests/test_display_text_fallback.py`.

**Interfaces:** Consume `RuntimeConfiguration` and `LocaleConfiguration` from `studio_runtime_client.py`. Produce `select_source(config: RuntimeConfiguration, language: str, field: DisplayField) -> SelectedText | None`, where `DisplayField` has `name`, `attribute`, `kind`, and `english_default`, and `SelectedText` has `text` and `language`.

- [ ] **Step 1: Write failing parameterized tests.** Build configurations with a local fixture shaped like `valid_configuration()` in `tests/test_studio_runtime_client.py` (do not import another test module). For each of the three V1 fields, assert target reviewed value, German source, English source, and SSF English default. Assert `de` matches `de-DE`, case-insensitive exact tag wins, `defaultLocale` wins among regional candidates, otherwise first matching locale with a present field wins. Add an unfamiliar code such as `sw` to prove no fixed language list. Assert a blank field is absent and storage mode `disabled` returns `None` for its question.

```python
REVISION = "sha256:" + "a" * 64

def make_config(locales: dict[str, str]) -> RuntimeConfiguration:
    entries = [
        {
            "locale": locale,
            "authenticatedHomeExplanationHtml": text,
            "guestExplanationHtml": text,
            "conversationContentStorageQuestionHtml": text,
        }
        for locale, text in locales.items()
    ]
    return RuntimeConfiguration.model_validate({
        "contractVersion": "1.0",
        "configurationRevision": REVISION,
        "authorizationRevision": REVISION,
        "tenant": {"id": "tenant-test", "displayName": "Test", "timeZone": "Europe/Berlin"},
        "branding": {"logo": None, "icon": None},
        "localization": {"defaultLocale": entries[0]["locale"], "locales": entries},
        "conversationContentStorage": {"mode": "ask"},
    })

@pytest.mark.parametrize("field_name", [
    "authenticatedHomeExplanationHtml",
    "guestExplanationHtml",
    "conversationContentStorageQuestionHtml",
])
def test_reviewed_studio_field_wins(field_name: str) -> None:
    config = make_config({"de-DE": "German", "sw-KE": "Reviewed"})
    selected = select_source(config, "sw", DISPLAY_FIELDS[field_name])
    assert selected == SelectedText("Reviewed", "sw")
```

- [ ] **Step 2: Run the new test module and verify its import fails.** `python -m pytest tests/test_display_text_fallback.py -q`.
- [ ] **Step 3: Add the minimal definitions and source-selection logic.** Use explicit definitions for the three V1 fields. Suggested English defaults are `<p>Smart Speech Flow helps people communicate across languages.</p>` for the two explanations and `<p>May this conversation be stored?</p>` for the storage question; have the proposal review confirm this product copy before code lands. Read values by the Pydantic field names, not by dumping and reparsing the whole configuration. Filter absent/blank values before selecting a locale; compare tags case-insensitively, then compare their primary subtags. For a missing target value, try German, English, and the field default in order. Preserve the input language string; only return text and its source language.

```python
@dataclass(frozen=True)
class DisplayField:
    name: str
    attribute: str
    kind: Literal["text", "html"]
    english_default: str

@dataclass(frozen=True)
class SelectedText:
    text: str
    language: str

DISPLAY_FIELDS = {
    "authenticatedHomeExplanationHtml": DisplayField(
        "authenticatedHomeExplanationHtml", "authenticated_home_explanation_html", "html",
        "<p>Smart Speech Flow helps people communicate across languages.</p>"),
    "guestExplanationHtml": DisplayField(
        "guestExplanationHtml", "guest_explanation_html", "html",
        "<p>Smart Speech Flow helps people communicate across languages.</p>"),
    "conversationContentStorageQuestionHtml": DisplayField(
        "conversationContentStorageQuestionHtml", "conversation_content_storage_question_html", "html",
        "<p>May this conversation be stored?</p>"),
}

def primary(tag: str) -> str:
    return tag.split("-", 1)[0].casefold()

def present(entry: LocaleConfiguration, field: DisplayField) -> bool:
    value = getattr(entry, field.attribute, None)
    return isinstance(value, str) and bool(value.strip())

def find_locale(config: RuntimeConfiguration, tag: str, field: DisplayField) -> LocaleConfiguration | None:
    locales = [entry for entry in config.localization.locales if present(entry, field)]
    exact = next((entry for entry in locales if entry.locale.casefold() == tag.casefold()), None)
    if exact is not None:
        return exact
    same_language = [entry for entry in locales if primary(entry.locale) == primary(tag)]
    return next((entry for entry in same_language if entry.locale.casefold() == config.localization.default_locale.casefold()), None) or (same_language[0] if same_language else None)

def select_source(
    config: RuntimeConfiguration, language: str, field: DisplayField
) -> SelectedText | None:
    if field.name == "conversationContentStorageQuestionHtml" and config.conversation_content_storage.mode == "disabled":
        return None
    for tag in (language, "de", "en"):
        entry = find_locale(config, tag, field)
        if entry is not None:
            return SelectedText(getattr(entry, field.attribute), primary(entry.locale))
    return SelectedText(field.english_default, "en")
```

- [ ] **Step 4: Run `python -m pytest tests/test_display_text_fallback.py -q`; verify the selection tests pass.**
- [ ] **Step 5: Commit the independently tested selection logic and tests.** `git add services/api_gateway/display_text_fallback.py tests/test_display_text_fallback.py && git commit -m 'feat: select Studio display text per language and field'`.

### Task 2: Translation and safe HTML

**Files:** Modify `services/api_gateway/display_text_fallback.py`, `tests/test_display_text_fallback.py`, `services/api_gateway/requirements.in`, and regenerated `services/api_gateway/requirements.txt`.

**Interfaces:** Consume `select_source(...)` from Task 1 and `SpeechServices.translate(payload)` from `speech_services.py`. Produce `resolve_display_texts(config: RuntimeConfiguration, language: str, speech: SpeechServices) -> dict[str, str | None]` keyed by the V1 Studio aliases.

- [ ] **Step 1: Add failing tests for each field's German, English, and SSF-English translation plus translation failure.** A recording speech stub returns `{"translations": ["..."]}` for a list payload; another raises a service error or returns an unusable response. Assert source language, target language, text-only payload, field-level all-or-nothing fallback, and unchanged conversation code. Test a plain-text `DisplayField` directly. Test nested `<p><strong>...</strong><a href="https://example.org">...</a></p>` and removal of `script`, `onclick`, and `javascript:`; assert no HTML tag or attribute is sent to translation. Assert storage mode `disabled` makes no request for its question.

```python
class RecordingSpeech:
    def __init__(self, translated: list[str]) -> None:
        self.translated = translated
        self.calls: list[dict[str, object]] = []

    def translate(self, payload: dict[str, object]):
        self.calls.append(payload)
        return FakeResponse({"translations": self.translated})

class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload

def test_html_translation_preserves_safe_structure() -> None:
    speech = RecordingSpeech(["Translated", "link"])
    config = make_config({"de-DE": "<p><strong>Quelle</strong><a href='https://example.org'>Link</a></p>"})
    result = resolve_display_texts(config, "sw", speech)
    assert "<strong>Translated</strong>" in result["guestExplanationHtml"]
    assert all("<" not in text for call in speech.calls for text in call["text"])
```

- [ ] **Step 2: Run `python -m pytest tests/test_display_text_fallback.py -q` and verify these tests fail for missing behavior.**
- [ ] **Step 3: Add `nh3` to `requirements.in` and regenerate the pinned lock using the repository's pip-tools command shown at the top of `requirements.txt`.** Install the locked Gateway requirements into the active test environment if needed. Keep the dependency limited to the Gateway.
- [ ] **Step 4: Implement translation and HTML handling.** Sanitize source fragments with an explicit allowlist of content tags (`p`, `br`, `strong`, `em`, `ul`, `ol`, `li`, `a`), `href` only on `a`, and safe URL schemes (`http`, `https`, `mailto`); strip script/style content. Parse the safe fragment with `html.parser.HTMLParser`, collect text nodes, translate them as one list per field through `speech.translate({"text": nodes, "source_lang": source, "target_lang": target})`, and serialize with `html.escape` for text and attribute values. Validate the response is a same-length list of nonblank strings. On any exception or invalid result, return the sanitized source fragment for that field. A matching primary source language skips translation. Plain text bypasses HTML parsing. Do not catch programming errors outside the translation/parsing boundary.

```python
def resolve_display_texts(
    config: RuntimeConfiguration, language: str, speech: SpeechServices
) -> dict[str, str | None]:
    output: dict[str, str | None] = {}
    for field in DISPLAY_FIELDS.values():
        selected = select_source(config, language, field)
        output[field.name] = None if selected is None else resolve_field(selected, language, field, speech)
    return output
```

- [ ] **Step 5: Run `python -m pytest tests/test_display_text_fallback.py -q` and `python -m pytest tests/test_studio_runtime_client.py tests/test_presentation_configuration.py -q`; inspect every failure.**
- [ ] **Step 6: Commit the translation implementation, dependency lock, and tests.** `git add services/api_gateway/display_text_fallback.py services/api_gateway/requirements.in services/api_gateway/requirements.txt tests/test_display_text_fallback.py && git commit -m 'feat: translate safe Studio display text with source fallback'`.

### Task 3: Document and verify the boundary

**Files:** Modify `docs/architecture/SYSTEM_ARCHITECTURE.md` and `openspec/changes/add-conversation-language-display-fallback/tasks.md`.

**Interfaces:** Document the `resolve_display_texts(...)` contract from Task 2; no runtime interface changes.

- [ ] **Step 1: Add a compact architecture section.** State that `/api/languages/supported` remains the conversation-language source; Studio locales provide reviewed display content; matching Studio text wins; missing fields use German Studio, English Studio, then SSF-owned English default; translation failure returns the selected safe source; disabled storage has no question; UI consumers and Studio changes are outside #300. State that future fields require an explicit text/HTML field definition and future languages require no fixed mapping table.
- [ ] **Step 2: Check the OpenSpec delta against the implementation and mark each `tasks.md` item complete only after its evidence exists.** Do not archive the change before deployment.
- [ ] **Step 3: Run `openspec validate add-conversation-language-display-fallback --strict`, `python -m pytest tests/test_display_text_fallback.py tests/test_studio_runtime_client.py tests/test_presentation_configuration.py -q`, and `git diff --check`; report results.**
- [ ] **Step 4: Commit documentation and completed OpenSpec checklist.** `git add docs/architecture/SYSTEM_ARCHITECTURE.md openspec/changes/add-conversation-language-display-fallback/tasks.md && git commit -m 'docs: specify conversation-language display fallback'`.
