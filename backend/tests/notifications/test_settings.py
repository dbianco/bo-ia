"""Plan 10: settings of the notifications."""
import pytest

from src.config.installation import (
    FiltroSeleccion,
    InstallationConfig,
    InstallationConfigInvalida,
    cargar_installation_config,
)
from src.notifications.settings import NotificationSettingsError, settings_from_environment

INSTALLATION = InstallationConfig(
    nombre="X", timezone="America/Argentina/Cordoba", filtros=[FiltroSeleccion(clave="provincia", etiqueta="Provincia")]
)
NAMES = ("PUBLIC_WEB_URL", "LINK_SECRET", "DIGEST_HOUR", "EMAIL_MAX_RETRIES")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults() -> None:
    settings = settings_from_environment(INSTALLATION)
    assert (settings.installation, settings.timezone, settings.digest_hour) == ("X", "America/Argentina/Cordoba", 7)
    assert settings.filter_labels == {"provincia": "Provincia"} and not settings.has_links


def test_from_the_environment(monkeypatch) -> None:
    for name, value in zip(NAMES, ("https://x.org/", " s ", "20", "3"), strict=True):
        monkeypatch.setenv(name, value)
    settings = settings_from_environment(INSTALLATION)
    assert (settings.public_url, settings.link_secret, settings.digest_hour, settings.max_retries) == ("https://x.org", "s", 20, 3)
    assert settings.has_links


@pytest.mark.parametrize(
    ("name", "value"),
    [("DIGEST_HOUR", "24"), ("DIGEST_HOUR", "x"), ("DIGEST_HOUR", "-1"), ("EMAIL_MAX_RETRIES", "-1"),
     ("PUBLIC_WEB_URL", "javascript:alert(1)"), ("PUBLIC_WEB_URL", "example.org")],
)  # fmt: skip
def test_a_wrong_setting_names_itself(monkeypatch, name, value) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(NotificationSettingsError, match=name):
        settings_from_environment(INSTALLATION)


def test_a_wrong_time_zone_stops_startup(tmp_path) -> None:
    path = tmp_path / "installation.yaml"
    path.write_text("nombre: x\ntimezone: America/Nowhere\n", encoding="utf-8")
    with pytest.raises(InstallationConfigInvalida):
        cargar_installation_config(path)


def test_the_shipped_installations_use_their_time_zone() -> None:
    from pathlib import Path

    config = Path(__file__).resolve().parents[3] / "config"
    for name in ("installation.yaml", "installation-licitaciones.yaml"):
        assert cargar_installation_config(config / name).timezone.startswith("America/Argentina/")
