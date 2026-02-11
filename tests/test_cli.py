"""Tests for the Agentic Bus CLI."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.cli import build_parser, main
from app.core.persistence.models import Base
from app.core.persistence.repository import AgentRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _generate_public_pem() -> str:
    private = Ed25519PrivateKey.generate()
    return private.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo,
    ).decode()


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Wire up an in-memory SQLite for the CLI to hit."""
    engine = create_engine("sqlite:///:memory:", echo=False, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(
        "app.core.persistence.repository.get_session",
        lambda: factory(),
    )
    # Also patch init_db to be a no-op (tables already exist)
    monkeypatch.setattr(
        "app.core.persistence.database.init_db",
        lambda *a, **kw: None,
    )
    return factory


@pytest.fixture()
def repo(db, monkeypatch):
    return AgentRepository()


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


class TestParser:
    def test_build_parser(self):
        parser = build_parser()
        assert parser.prog == "agbus"

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "agbus" in out

    def test_no_command_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main([])  # no command → prints help, exits 0
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "commands" in out.lower() or "usage" in out.lower()


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


class TestConfigShow:
    def test_config_show(self, capsys):
        main(["config", "show"])
        out = capsys.readouterr().out
        assert "AGBUS_HOST" in out
        assert "AGBUS_PORT" in out
        assert "AGBUS_LLM_PROVIDER" in out
        assert "AGBUS_DATABASE_URL" in out


# ---------------------------------------------------------------------------
# config init
# ---------------------------------------------------------------------------


class TestConfigInit:
    def test_config_init_creates_file(self, tmp_path, monkeypatch):
        target = tmp_path / ".env"
        # Ensure the .env.example can be found – create a minimal one
        example = tmp_path / ".env.example"
        example.write_text("# example\nAGBUS_HOST=0.0.0.0\n")

        monkeypatch.chdir(tmp_path)
        # Patch the fallback lookup to find our example
        main(["config", "init", "-o", str(target), "--force"])
        assert target.exists()
        assert "AGBUS_HOST" in target.read_text()

    def test_config_init_refuses_overwrite(self, tmp_path, capsys):
        target = tmp_path / ".env"
        target.write_text("existing")
        with pytest.raises(SystemExit) as exc:
            main(["config", "init", "-o", str(target)])
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------


class TestHelp:
    def test_help_overview(self, capsys):
        main(["help"])
        out = capsys.readouterr().out
        assert "Agentic Bus Protocol" in out
        assert "Semantic Discovery" in out

    def test_help_architecture(self, capsys):
        main(["help", "architecture"])
        out = capsys.readouterr().out
        assert "Session Lifecycle" in out
        assert "IBAC" in out

    def test_help_agents(self, capsys):
        main(["help", "agents"])
        out = capsys.readouterr().out
        assert "Capability Declaration" in out
        assert "AgentCapability" in out

    def test_help_persistence(self, capsys):
        main(["help", "persistence"])
        out = capsys.readouterr().out
        assert "Challenge-Response Auth" in out
        assert "Ed25519" in out

    def test_help_admin(self, capsys):
        main(["help", "admin"])
        out = capsys.readouterr().out
        assert "Who is an Admin" in out
        assert "AGBUS_ADMIN_SUBJECTS" in out

    def test_help_quickstart(self, capsys):
        main(["help", "quickstart"])
        out = capsys.readouterr().out
        assert "Quick Start Guide" in out
        assert "Step 1" in out

    def test_help_invalid_topic(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["help", "bogus"])
        assert exc.value.code == 2  # argparse returns 2 for invalid choice


# ---------------------------------------------------------------------------
# db init
# ---------------------------------------------------------------------------


class TestDbInit:
    def test_db_init(self, capsys, db):
        main(["db", "init"])
        out = capsys.readouterr().out
        assert "initialised" in out.lower() or "✓" in out


# ---------------------------------------------------------------------------
# agent commands
# ---------------------------------------------------------------------------


class TestAgentList:
    def test_list_empty(self, capsys, db):
        main(["agent", "list"])
        out = capsys.readouterr().out
        assert "No persistent agents" in out

    def test_list_with_agents(self, capsys, repo, db):
        repo.enrol("agent-1", _generate_public_pem(), semantic_description="First")
        repo.enrol("agent-2", _generate_public_pem(), semantic_description="Second")
        main(["agent", "list"])
        out = capsys.readouterr().out
        assert "agent-1" in out
        assert "agent-2" in out
        assert "2 agent(s)" in out

    def test_list_filter_by_status(self, capsys, repo, db):
        repo.enrol("a1", _generate_public_pem())
        repo.enrol("a2", _generate_public_pem())
        repo.approve("a2")
        main(["agent", "list", "--status", "approved"])
        out = capsys.readouterr().out
        assert "a2" in out
        assert "1 agent(s)" in out

    def test_list_invalid_status(self, capsys, db):
        with pytest.raises(SystemExit) as exc:
            main(["agent", "list", "--status", "bogus"])
        assert exc.value.code == 1


class TestAgentShow:
    def test_show_existing(self, capsys, repo, db):
        repo.enrol("show-me", _generate_public_pem(), semantic_description="Hello")
        main(["agent", "show", "show-me"])
        out = capsys.readouterr().out
        assert "show-me" in out
        assert "Hello" in out

    def test_show_missing(self, capsys, db):
        with pytest.raises(SystemExit) as exc:
            main(["agent", "show", "ghost"])
        assert exc.value.code == 1


class TestAgentApprove:
    def test_approve(self, capsys, repo, db):
        repo.enrol("ap-1", _generate_public_pem())
        main(["agent", "approve", "ap-1"])
        out = capsys.readouterr().out
        assert "approved" in out.lower()
        assert repo.get("ap-1").status.value == "approved"

    def test_approve_nonexistent(self, capsys, db):
        with pytest.raises(SystemExit) as exc:
            main(["agent", "approve", "nope"])
        assert exc.value.code == 1


class TestAgentReject:
    def test_reject(self, capsys, repo, db):
        repo.enrol("rej-1", _generate_public_pem())
        main(["agent", "reject", "rej-1"])
        out = capsys.readouterr().out
        assert "rejected" in out.lower()

    def test_reject_nonexistent(self, capsys, db):
        with pytest.raises(SystemExit) as exc:
            main(["agent", "reject", "nope"])
        assert exc.value.code == 1


class TestAgentRevoke:
    def test_revoke(self, capsys, repo, db):
        repo.enrol("rev-1", _generate_public_pem())
        repo.approve("rev-1")
        main(["agent", "revoke", "rev-1"])
        out = capsys.readouterr().out
        assert "revoked" in out.lower()

    def test_revoke_nonexistent(self, capsys, db):
        with pytest.raises(SystemExit) as exc:
            main(["agent", "revoke", "nope"])
        assert exc.value.code == 1


class TestAgentDelete:
    def test_delete_with_yes(self, capsys, repo, db):
        repo.enrol("del-1", _generate_public_pem())
        main(["agent", "delete", "del-1", "-y"])
        out = capsys.readouterr().out
        assert "deleted" in out.lower()
        assert repo.get("del-1") is None

    def test_delete_nonexistent(self, capsys, db):
        with pytest.raises(SystemExit) as exc:
            main(["agent", "delete", "nope", "-y"])
        assert exc.value.code == 1

    def test_delete_cancelled(self, capsys, repo, db, monkeypatch):
        repo.enrol("del-2", _generate_public_pem())
        monkeypatch.setattr("builtins.input", lambda _: "n")
        main(["agent", "delete", "del-2"])
        out = capsys.readouterr().out
        assert "Cancelled" in out
        assert repo.get("del-2") is not None


# ---------------------------------------------------------------------------
# install wizard
# ---------------------------------------------------------------------------


class TestInstall:
    """Tests for the ``agbus install`` interactive setup wizard."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch, db):
        """Run every install test in a tmp dir with a patched DB."""
        monkeypatch.chdir(tmp_path)
        self.tmp = tmp_path

    # Helper to feed answers to the wizard
    @staticmethod
    def _make_input_fn(answers: list[str]):
        """Return an ``input()`` replacement that pops answers in order."""
        it = iter(answers)
        def _input(prompt=""):
            try:
                return next(it)
            except StopIteration:
                return ""
        return _input

    def test_install_openai_defaults_no_start(self, capsys, monkeypatch):
        """Walk through with all defaults (openai), decline to start."""
        answers = [
            "",           # provider choice → default openai
            "",           # model → gpt-4o-mini
            "",           # temperature → 0.0
            "",           # API key (secret → getpass)
            "",           # host → 0.0.0.0
            "",           # port → 8765
            "",           # log level → INFO
            "",           # db url → sqlite:///agbus_agents.db
            "n",          # auto-approve → no
            "n",          # configure OIDC → no
            "n",          # start server → no
        ]
        monkeypatch.setattr("builtins.input", self._make_input_fn(answers))
        monkeypatch.setattr("getpass.getpass", lambda _: "")

        main(["install", "--force"])

        env_file = self.tmp / ".env"
        assert env_file.exists()
        content = env_file.read_text()
        assert "AGBUS_LLM_PROVIDER=openai" in content
        assert "AGBUS_LLM_MODEL=gpt-4o-mini" in content
        assert "AGBUS_HOST=0.0.0.0" in content
        assert "AGBUS_PORT=8765" in content
        assert "AGBUS_DATABASE_URL=sqlite:///agbus_agents.db" in content
        assert "AGBUS_AGENT_AUTO_APPROVE=false" in content

        out = capsys.readouterr().out
        assert "Setup Wizard" in out
        assert "agbus serve" in out  # told to run serve

    def test_install_anthropic_with_auth(self, capsys, monkeypatch):
        """Pick anthropic, fill in OIDC, skip start."""
        answers = [
            "2",                     # provider → anthropic
            "claude-sonnet-4-20250514",        # model
            "0.3",                   # temperature
            # (API key via getpass)
            "127.0.0.1",             # host
            "9999",                  # port
            "2",                     # log level → INFO (default)
            "sqlite:///test.db",     # db url
            "y",                     # auto-approve
            "y",                     # configure OIDC
            "https://issuer.test",   # oidc issuer
            "my-audience",           # oidc audience
            "sub1,sub2",             # admin subjects
            "admin",                 # admin role
            "groups",                # admin role claim
            "n",                     # start → no
        ]
        monkeypatch.setattr("builtins.input", self._make_input_fn(answers))
        monkeypatch.setattr("getpass.getpass", lambda _: "sk-ant-secret")

        main(["install", "--force"])

        content = (self.tmp / ".env").read_text()
        assert "AGBUS_LLM_PROVIDER=anthropic" in content
        assert "ANTHROPIC_API_KEY=sk-ant-secret" in content
        assert "AGBUS_HOST=127.0.0.1" in content
        assert "AGBUS_PORT=9999" in content
        assert "AGBUS_LLM_TEMPERATURE=0.3" in content
        assert "AGBUS_AGENT_AUTO_APPROVE=true" in content
        assert "AGBUS_OIDC_ISSUER=https://issuer.test" in content
        assert "AGBUS_OIDC_AUDIENCE=my-audience" in content
        assert "AGBUS_ADMIN_SUBJECTS=sub1,sub2" in content
        assert "AGBUS_ADMIN_ROLE=admin" in content
        assert "AGBUS_ADMIN_ROLE_CLAIM=groups" in content

    def test_install_ollama(self, capsys, monkeypatch):
        """Ollama provider uses base URL instead of API key."""
        answers = [
            "4",                              # provider → ollama
            "mistral",                        # model
            "0.7",                            # temperature
            "http://myhost:11434",            # base url (not secret)
            "",                               # host default
            "",                               # port default
            "",                               # log level default
            "",                               # db url default
            "n",                              # auto-approve
            "n",                              # OIDC
            "n",                              # start
        ]
        monkeypatch.setattr("builtins.input", self._make_input_fn(answers))

        main(["install", "--force"])

        content = (self.tmp / ".env").read_text()
        assert "AGBUS_LLM_PROVIDER=ollama" in content
        assert "AGBUS_LLM_MODEL=mistral" in content
        assert "AGBUS_OLLAMA_BASE_URL=http://myhost:11434" in content
        # Should NOT have any *_API_KEY
        assert "API_KEY" not in content

    def test_install_azure(self, capsys, monkeypatch):
        """Azure provider needs extra keys."""
        answers = [
            "5",                              # provider → azure
            "gpt-4",                          # model
            "0.0",                            # temperature
            # (API key via getpass)
            "https://my.openai.azure.com/",   # endpoint
            "gpt-4-deploy",                   # deployment
            "2024-06-01",                     # api version
            "",                               # host default
            "",                               # port default
            "",                               # log level default
            "",                               # db url default
            "n",                              # auto-approve
            "n",                              # OIDC
            "n",                              # start
        ]
        monkeypatch.setattr("builtins.input", self._make_input_fn(answers))
        monkeypatch.setattr("getpass.getpass", lambda _: "az-key-123")

        main(["install", "--force"])

        content = (self.tmp / ".env").read_text()
        assert "AGBUS_LLM_PROVIDER=azure" in content
        assert "AZURE_OPENAI_API_KEY=az-key-123" in content
        assert "AZURE_OPENAI_ENDPOINT=https://my.openai.azure.com/" in content
        assert "AZURE_OPENAI_DEPLOYMENT=gpt-4-deploy" in content
        assert "AZURE_OPENAI_API_VERSION=2024-06-01" in content

    def test_install_refuses_overwrite_without_force(self, capsys, monkeypatch):
        """If .env exists and user declines overwrite → exit 0."""
        (self.tmp / ".env").write_text("existing")
        answers = [
            "",    # provider default
            "",    # model default
            "",    # temperature default
            "",    # host
            "",    # port
            "",    # log level
            "",    # db url
            "n",   # auto-approve
            "n",   # OIDC
            "n",   # overwrite → no
        ]
        monkeypatch.setattr("builtins.input", self._make_input_fn(answers))
        monkeypatch.setattr("getpass.getpass", lambda _: "")

        with pytest.raises(SystemExit) as exc:
            main(["install"])
        assert exc.value.code == 0
        # Original file preserved
        assert (self.tmp / ".env").read_text() == "existing"

    def test_install_force_overwrites(self, capsys, monkeypatch):
        """--force skips the overwrite prompt."""
        (self.tmp / ".env").write_text("old")
        answers = [
            "",  "",  "",   # provider defaults
            "",  "",  "",  "",  # server defaults
            "n",             # auto-approve
            "n",             # OIDC
            "n",             # start
        ]
        monkeypatch.setattr("builtins.input", self._make_input_fn(answers))
        monkeypatch.setattr("getpass.getpass", lambda _: "")

        main(["install", "--force"])

        content = (self.tmp / ".env").read_text()
        assert "AGBUS_LLM_PROVIDER=openai" in content
        assert content != "old"

    def test_install_writes_db_init(self, capsys, monkeypatch):
        """Wizard should call init_db and report success."""
        answers = [""] * 7 + ["n", "n", "n"]
        monkeypatch.setattr("builtins.input", self._make_input_fn(answers))
        monkeypatch.setattr("getpass.getpass", lambda _: "")

        main(["install", "--force"])

        out = capsys.readouterr().out
        assert "Database initialised" in out

    def test_install_custom_output_path(self, capsys, monkeypatch):
        """Can write to a custom path with -o."""
        target = self.tmp / "custom.env"
        answers = [""] * 7 + ["n", "n", "n"]
        monkeypatch.setattr("builtins.input", self._make_input_fn(answers))
        monkeypatch.setattr("getpass.getpass", lambda _: "")

        main(["install", "-o", str(target), "--force"])

        assert target.exists()
        assert "AGBUS_LLM_PROVIDER" in target.read_text()

    def test_install_google_provider(self, capsys, monkeypatch):
        """Google provider uses GOOGLE_API_KEY."""
        answers = [
            "3",        # google
            "",         # model default
            "",         # temp default
            # (key via getpass)
            "",  "",    # host, port
            "",         # log level
            "",         # db url
            "n",        # auto-approve
            "n",        # OIDC
            "n",        # start
        ]
        monkeypatch.setattr("builtins.input", self._make_input_fn(answers))
        monkeypatch.setattr("getpass.getpass", lambda _: "google-key-abc")

        main(["install", "--force"])

        content = (self.tmp / ".env").read_text()
        assert "AGBUS_LLM_PROVIDER=google" in content
        assert "GOOGLE_API_KEY=google-key-abc" in content
        assert "AGBUS_LLM_MODEL=gemini-2.0-flash" in content
