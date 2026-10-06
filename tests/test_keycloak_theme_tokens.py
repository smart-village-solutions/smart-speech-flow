"""The Keycloak login theme must take brand colours from the frontend tokens (#346)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "services" / "keycloak" / "theme" / "login"
LOGIN_CSS = THEME / "resources" / "css" / "login.css"
TOKENS = ROOT / "services" / "frontend" / "src" / "ui" / "styles" / "theme.css"
DOCKERFILE = ROOT / "services" / "keycloak" / "Dockerfile"


def _root_tokens() -> set[str]:
    root_block = re.search(r":root\s*\{(.*?)\n\}", TOKENS.read_text(), re.DOTALL)
    assert root_block
    return set(re.findall(r"(--[a-z0-9-]+):", root_block.group(1)))


COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(|\b(?:white|black)\b")
# theme.css has no shadow tokens, so the two box shadows keep their literal colour.
LITERAL_COLOUR_PROPERTIES = {"box-shadow"}


def _without_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _declarations(css: str) -> list[tuple[str, str]]:
    """Every `property: value` pair, wherever it is nested; selectors never match."""
    pattern = r"([a-z-]+)\s*:\s*([^;{}]+?)\s*(?=[;}])"
    return re.findall(pattern, _without_comments(css))


def test_login_css_states_no_colour_of_its_own() -> None:
    literal = [
        f"{name}: {value}"
        for name, value in _declarations(LOGIN_CSS.read_text())
        if name not in LITERAL_COLOUR_PROPERTIES and COLOUR.search(value)
    ]

    assert literal == []


def test_every_token_login_css_uses_exists_in_theme_css() -> None:
    stylesheet = LOGIN_CSS.read_text()
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", stylesheet))
    own = set(re.findall(r"(--[a-z0-9-]+):", stylesheet))

    assert used - own <= _root_tokens()
    assert {"--surface-page", "--fg-strong", "--surface-card"} <= used


def test_the_image_ships_theme_css_before_login_css() -> None:
    assert (
        "COPY services/frontend/src/ui/styles/theme.css "
        "/opt/keycloak/themes/kasseldialog/login/resources/css/theme.css"
    ) in DOCKERFILE.read_text()
    assert "styles=css/theme.css css/login.css" in (THEME / "theme.properties").read_text()


def test_theme_css_holds_only_custom_properties_the_login_page_can_load() -> None:
    """Keycloak ships theme.css verbatim. Anything beyond token declarations --
    a rule, a Tailwind directive, a media query -- would silently restyle or
    break the production login page."""
    stylesheet = _without_comments(TOKENS.read_text())
    blocks = re.findall(r"([^{}]*)\{([^{}]*)\}", stylesheet)

    assert re.sub(r"[^{}]*\{[^{}]*\}", "", stylesheet).strip() == ""
    assert {selector.strip() for selector, _ in blocks} == {":root", ".dark"}
    for _, body in blocks:
        statements = [statement.strip() for statement in body.split(";") if statement.strip()]
        assert all(re.fullmatch(r"--[a-z0-9-]+\s*:[^:]+", statement) for statement in statements)
