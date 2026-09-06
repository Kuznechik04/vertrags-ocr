import pytest

from app.core.config import INSECURE_DEFAULT_SECRET_KEY, Settings


def test_settings_rejects_default_secret_outside_development():
    with pytest.raises(Exception):
        Settings(environment="production", secret_key=INSECURE_DEFAULT_SECRET_KEY)


def test_settings_allows_default_secret_in_development():
    settings = Settings(environment="development", secret_key=INSECURE_DEFAULT_SECRET_KEY)
    assert settings.secret_key == INSECURE_DEFAULT_SECRET_KEY


def test_settings_allows_non_development_with_real_secret():
    settings = Settings(environment="production", secret_key="a-real-random-secret")
    assert settings.environment == "production"
