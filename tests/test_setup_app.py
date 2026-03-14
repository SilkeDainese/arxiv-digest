from pathlib import Path
import tomllib

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_setup_app_renders_without_streamlit_exceptions(monkeypatch):
    """Smoke-test the setup wizard with a fake server-side Gemini key."""
    monkeypatch.chdir(ROOT / "setup")
    monkeypatch.syspath_prepend(str(ROOT / "setup"))

    app = AppTest.from_file(str(ROOT / "setup" / "app.py"))
    app.secrets["GEMINI_API_KEY"] = "test-server-key"

    app.run(timeout=10)
    assert len(app.exception) == 0

    app.text_input(key="user_email_rl").set_value("tester@example.com")
    app.run(timeout=20)

    assert len(app.exception) == 0
    assert [expander.label for expander in app.expander] == [
        "**1. Your ORCID**",
        "**2. Your Profile**",
        "**3. Your Research Description**",
        "**4. arXiv Categories**",
        "**5. Keywords**",
        "**6. Research Authors**",
        "**7. Colleagues**",
        "**8. Digest Mode & Schedule**",
        "**9. Email Provider**",
        "**10. Preview & Download**",
    ]


def test_root_streamlit_theme_matches_setup_theme():
    """Theme config must exist at repo root for Streamlit Cloud."""
    root_theme = ROOT / ".streamlit" / "config.toml"
    setup_theme = ROOT / "setup" / ".streamlit" / "config.toml"

    assert tomllib.loads(root_theme.read_text()) == tomllib.loads(
        setup_theme.read_text()
    )
