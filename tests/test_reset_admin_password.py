import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex import reset_admin_password as command
from skardex.config import Settings, settings
from skardex.models import User, UserRole
from skardex.security import verify_password
from skardex.services.user_service import MIN_PASSWORD_LENGTH, WeakPasswordError

NEW_PASSWORD = "recovered-pass"


def test_reset_updates_existing_admin_and_flags_it(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H5-01, EARS-H5-03"""
    admin = command.reset_admin_password(db_session, NEW_PASSWORD)

    assert admin.id == admin_user.id
    assert verify_password(NEW_PASSWORD, admin_user.password_hash)
    assert not verify_password("admin-pass", admin_user.password_hash)
    assert admin_user.must_change_password is True
    assert db_session.query(User).filter(User.role == UserRole.ADMIN).count() == 1


def test_admin_is_forced_to_choose_a_new_password_at_next_login(
    db_session: Session, admin_user: User, client: TestClient
) -> None:
    """EARS-H5-03 (reuses the forced-change flow of the temporary passwords)"""
    command.reset_admin_password(db_session, NEW_PASSWORD)

    response = client.post(
        "/login",
        data={"username": admin_user.username, "password": NEW_PASSWORD},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/account/set-password"


def test_reset_without_admin_fails_and_creates_nothing(
    db_session: Session, operario_user: User
) -> None:
    """EARS-H5-02"""
    with pytest.raises(command.NoAdminError):
        command.reset_admin_password(db_session, NEW_PASSWORD)

    assert db_session.query(User).filter(User.role == UserRole.ADMIN).count() == 0
    assert db_session.query(User).count() == 1


@pytest.mark.parametrize("missing", [None, ""])
def test_reset_requires_a_password(
    db_session: Session, admin_user: User, missing: str | None
) -> None:
    old_hash = admin_user.password_hash

    with pytest.raises(command.MissingResetPasswordError):
        command.reset_admin_password(db_session, missing)

    assert admin_user.password_hash == old_hash
    assert admin_user.must_change_password is False


def test_reset_rejects_a_password_shorter_than_the_minimum(
    db_session: Session, admin_user: User
) -> None:
    old_hash = admin_user.password_hash

    with pytest.raises(WeakPasswordError):
        command.reset_admin_password(db_session, "a" * (MIN_PASSWORD_LENGTH - 1))

    assert admin_user.password_hash == old_hash
    assert admin_user.must_change_password is False


def test_setting_is_read_from_admin_reset_password_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EARS-H5-01"""
    for name, value in {
        "DATABASE_URL": "sqlite://",
        "SECRET_KEY": "x",
        "SEED_ADMIN_USERNAME": "admin",
        "SEED_ADMIN_PASSWORD": "x",
    }.items():
        monkeypatch.setenv(name, value)

    monkeypatch.delenv("ADMIN_RESET_PASSWORD", raising=False)
    assert Settings(_env_file=None).admin_reset_password is None  # type: ignore[call-arg]

    monkeypatch.setenv("ADMIN_RESET_PASSWORD", NEW_PASSWORD)
    assert Settings(_env_file=None).admin_reset_password == NEW_PASSWORD  # type: ignore[call-arg]


def test_main_resets_admin_and_does_not_print_the_password(
    db_session: Session,
    admin_user: User,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """EARS-H5-01"""
    monkeypatch.setattr(command, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(settings, "admin_reset_password", NEW_PASSWORD)

    assert command.main() == 0

    output = capsys.readouterr().out
    assert admin_user.username in output
    assert NEW_PASSWORD not in output
    assert verify_password(NEW_PASSWORD, admin_user.password_hash)


def test_main_reports_missing_admin_with_a_clear_message(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """EARS-H5-02"""
    monkeypatch.setattr(command, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(settings, "admin_reset_password", NEW_PASSWORD)

    assert command.main() == 1

    assert "No admin exists yet" in capsys.readouterr().out


def test_main_reports_missing_password_with_a_clear_message(
    db_session: Session,
    admin_user: User,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(command, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(settings, "admin_reset_password", None)

    assert command.main() == 1

    assert "Set ADMIN_RESET_PASSWORD" in capsys.readouterr().out
