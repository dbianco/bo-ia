"""Every environment variable is documented where people look for it."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
EXAMPLES = [".env.example", ".env.licitaciones.example"]
# Composed in code from the groups of limits.
COMPOSED = {f"RATE_LIMIT_{g}" for g in ("SEARCH", "RATINGS", "REGISTER", "LOGIN", "PUBLIC")}
# Read by libraries.
BY_LIBRARIES = {"FORWARDED_ALLOW_IPS"}


def _in_code() -> set[str]:
    names = set(COMPOSED)
    for path in [*(ROOT / "backend/src").rglob("*.py"), ROOT / "web/app.py"]:
        text = path.read_text(encoding="utf-8")
        names |= set(re.findall(r'environ(?:\.get\(|\[)\s*"([A-Z_]+)"', text))
        names |= set(re.findall(r'(?:VARIABLE = |_whole_number\()"([A-Z_]+)"', text))
    return names


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _example(name: str) -> dict[str, str]:
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def test_the_search_for_variables_finds_them() -> None:
    assert {"DATABASE_URL", "OPERATOR_TOKEN", "LINK_SECRET", "DIGEST_HOUR", "BACKEND_INTERNAL_URL"} <= _in_code()


@pytest.mark.parametrize("name", sorted(_in_code() | BY_LIBRARIES))
def test_a_variable_is_in_the_readme_the_examples_and_compose(name: str) -> None:
    assert f"`{name}`" in README
    for example in EXAMPLES:
        assert name in _example(example), example
    services = _compose()["services"]
    assert any(name in services[s]["environment"] for s in ("backend", "web"))


def test_compose_uses_no_variable_that_is_not_in_the_examples() -> None:
    used = set(re.findall(r"\$\{([A-Z_]+)", (ROOT / "docker-compose.yml").read_text(encoding="utf-8")))
    for example in EXAMPLES:
        assert used <= set(_example(example)), example


def test_the_examples_have_no_secrets() -> None:
    for example in EXAMPLES:
        values = _example(example)
        assert values["OPERATOR_TOKEN"] == values["LINK_SECRET"] == values["SMTP_PASSWORD"] == ""


def test_the_values_of_the_examples_are_valid(monkeypatch) -> None:
    from src.api.rate_limit import load_limits
    from src.config.installation import InstallationConfig
    from src.notifications.settings import settings_from_environment

    for example in EXAMPLES:
        for name, value in _example(example).items():
            if name not in ("DATABASE_URL", "SMTP_HOST"):
                monkeypatch.setenv(name, value)
        load_limits()
        settings_from_environment(InstallationConfig(nombre="x"))


def test_the_documents_that_the_readme_links_to_exist() -> None:
    for target in re.findall(r"\]\(([^)#:]+)(?:#[^)]*)?\)", README):
        assert (ROOT / target).exists(), target


def test_the_sections_that_the_readme_links_to_exist() -> None:
    def anchors(text: str) -> set[str]:
        titles = re.findall(r"^#+ (.+)$", re.sub(r"```.*?```", "", text, flags=re.S), flags=re.M)
        return {re.sub(r"[^\w\- ]", "", t.lower()).replace(" ", "-") for t in titles}

    for target, anchor in re.findall(r"\]\(([^)#:]*)#([^)]+)\)", README):
        text = (ROOT / target).read_text(encoding="utf-8") if target else README
        assert anchor in anchors(text), f"{target}#{anchor}"


def test_the_endpoints_are_in_the_readme() -> None:
    from src.api.main import ROUTERS

    for router in ROUTERS:
        for route in router.routes:
            path = re.sub(r"\{(\w+_)?id\}", "{id}", route.path)
            for method in route.methods:
                assert f"`{method} {path}`" in README, f"{method} {path}"
