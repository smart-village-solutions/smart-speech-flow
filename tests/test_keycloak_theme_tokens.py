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


def test_login_css_has_no_hex_colours() -> None:
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", LOGIN_CSS.read_text()) == []


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


def test_theme_css_stays_plain_css_the_login_page_can_load() -> None:
    """Keycloak ships theme.css verbatim; a Tailwind directive or a media query
    there would silently change or break the production login page."""
    stylesheet = re.sub(r"/\*.*?\*/", "", TOKENS.read_text(), flags=re.DOTALL)

    assert re.findall(r"@[a-z-]+", stylesheet) == []
