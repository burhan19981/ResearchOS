from pathlib import Path

from researchos.db.config import DEFAULT_DATABASE_URL, load_database_config


def test_default_database_url_is_sqlite_outside_src(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("researchos.db.config.load_dotenv", lambda *a, **k: None)
    config = load_database_config()
    assert config.url == DEFAULT_DATABASE_URL
    assert config.url.startswith("sqlite:///")
    assert "/data/researchos.db" in config.url
    assert "/src/" not in config.url


def test_database_url_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///somewhere/else.db")
    monkeypatch.setattr("researchos.db.config.load_dotenv", lambda *a, **k: None)
    config = load_database_config()
    assert config.url == "sqlite:///somewhere/else.db"


def test_postgres_style_url_is_accepted_without_code_changes(monkeypatch):
    # This does not connect to Postgres — it only proves the config layer
    # treats the URL as an opaque SQLAlchemy connection string.
    pg_url = "postgresql+psycopg://user:pass@localhost:5432/researchos"
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setattr("researchos.db.config.load_dotenv", lambda *a, **k: None)
    config = load_database_config()
    assert config.url == pg_url


def test_db_echo_flag_defaults_false(monkeypatch):
    monkeypatch.delenv("RESEARCHOS_DB_ECHO", raising=False)
    monkeypatch.setattr("researchos.db.config.load_dotenv", lambda *a, **k: None)
    config = load_database_config()
    assert config.echo is False


def test_db_echo_flag_reads_env(monkeypatch):
    monkeypatch.setenv("RESEARCHOS_DB_ECHO", "true")
    monkeypatch.setattr("researchos.db.config.load_dotenv", lambda *a, **k: None)
    config = load_database_config()
    assert config.echo is True
