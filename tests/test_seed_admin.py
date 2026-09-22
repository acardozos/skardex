import pytest
from sqlalchemy.orm import Session

from skardex import seed_admin as command
from skardex.config import settings
from skardex.models import User, UserRole
from skardex.security import verify_password

USERNAME = "seeded-admin"
PASSWORD = "seeded-pass"


@pytest.fixture(autouse=True)
def _seed_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route the command at the session under test, with a fixed username
    and password so tests don't depend on whatever is in `.env`."""
    monkeypatch.setattr(settings, "seed_admin_username", USERNAME)
    monkeypatch.setattr(settings, "seed_admin_password", PASSWORD)


def test_creates_the_admin_with_a_hashed_password(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(command, "SessionLocal", lambda: db_session)

    command.seed_admin()

    admin = db_session.query(User).filter(User.role == UserRole.ADMIN).one()
    assert admin.username == USERNAME
    assert admin.is_active is True
    assert admin.password_hash != PASSWORD  # stored hashed, not in the clear
    assert verify_password(PASSWORD, admin.password_hash)


def test_does_not_print_the_password(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(command, "SessionLocal", lambda: db_session)

    command.seed_admin()

    output = capsys.readouterr().out
    assert USERNAME in output
    assert PASSWORD not in output


def test_skips_and_creates_nothing_if_an_admin_already_exists(
    db_session: Session, admin_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(command, "SessionLocal", lambda: db_session)

    command.seed_admin()

    assert db_session.query(User).filter(User.role == UserRole.ADMIN).count() == 1
    admin = db_session.query(User).filter(User.role == UserRole.ADMIN).one()
    assert admin.id == admin_user.id  # the existing one, not a new one
    assert admin.username != USERNAME


def test_skip_message_names_the_existing_admin_and_not_the_new_password(
    db_session: Session,
    admin_user: User,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(command, "SessionLocal", lambda: db_session)

    command.seed_admin()

    output = capsys.readouterr().out
    assert admin_user.username in output
    assert PASSWORD not in output


def test_an_existing_operario_does_not_block_seeding_the_admin(
    db_session: Session, operario_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check is for an admin specifically, not for any user at all."""
    monkeypatch.setattr(command, "SessionLocal", lambda: db_session)

    command.seed_admin()

    assert db_session.query(User).filter(User.role == UserRole.ADMIN).count() == 1
    assert db_session.query(User).count() == 2


def test_running_it_twice_only_creates_one_admin(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(command, "SessionLocal", lambda: db_session)

    command.seed_admin()
    command.seed_admin()

    assert db_session.query(User).filter(User.role == UserRole.ADMIN).count() == 1
