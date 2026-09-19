import pytest
from sqlalchemy.orm import Session

from skardex.models import User
from skardex.security import verify_password
from skardex.services.user_service import (
    MIN_PASSWORD_LENGTH,
    TEMPORARY_PASSWORD_ALPHABET,
    CannotResetOwnPasswordError,
    InactiveUserError,
    WeakPasswordError,
    WrongCurrentPasswordError,
    change_own_password,
    reset_password_to_temporary,
    set_new_password_after_temporary,
)


def test_change_own_password_updates_hash(
    db_session: Session, operario_user: User
) -> None:
    """EARS-H1-02"""
    change_own_password(
        db_session,
        operario_user,
        current_password="operario-pass",
        new_password="brand-new-pass",
    )

    assert verify_password("brand-new-pass", operario_user.password_hash)
    assert not verify_password("operario-pass", operario_user.password_hash)


def test_change_own_password_rejects_wrong_current_password(
    db_session: Session, operario_user: User
) -> None:
    """EARS-H1-03"""
    with pytest.raises(WrongCurrentPasswordError):
        change_own_password(
            db_session,
            operario_user,
            current_password="not-the-password",
            new_password="brand-new-pass",
        )

    assert verify_password("operario-pass", operario_user.password_hash)


def test_change_own_password_rejects_weak_new_password(
    db_session: Session, operario_user: User
) -> None:
    """EARS-H1-04"""
    with pytest.raises(WeakPasswordError):
        change_own_password(
            db_session,
            operario_user,
            current_password="operario-pass",
            new_password="a" * (MIN_PASSWORD_LENGTH - 1),
        )

    assert verify_password("operario-pass", operario_user.password_hash)


def test_change_own_password_checks_current_password_before_strength(
    db_session: Session, operario_user: User
) -> None:
    with pytest.raises(WrongCurrentPasswordError):
        change_own_password(
            db_session,
            operario_user,
            current_password="not-the-password",
            new_password="short",
        )


def test_reset_password_to_temporary_sets_flag_and_hash(
    db_session: Session, operario_user: User
) -> None:
    """EARS-H3-02"""
    temporary = reset_password_to_temporary(db_session, operario_user)

    assert len(temporary) == MIN_PASSWORD_LENGTH
    assert set(temporary) <= set(TEMPORARY_PASSWORD_ALPHABET)
    assert verify_password(temporary, operario_user.password_hash)
    assert not verify_password("operario-pass", operario_user.password_hash)
    assert operario_user.must_change_password is True


def test_reset_password_to_temporary_is_random(
    db_session: Session, operario_user: User
) -> None:
    first = reset_password_to_temporary(db_session, operario_user)
    second = reset_password_to_temporary(db_session, operario_user)

    assert first != second


def test_reset_password_to_temporary_refuses_admin(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H3-04 (service-level guard)"""
    with pytest.raises(CannotResetOwnPasswordError):
        reset_password_to_temporary(db_session, admin_user)

    assert verify_password("admin-pass", admin_user.password_hash)
    assert admin_user.must_change_password is False


def test_reset_password_to_temporary_refuses_inactive_user(
    db_session: Session, inactive_user: User
) -> None:
    """EARS-H3-05"""
    with pytest.raises(InactiveUserError):
        reset_password_to_temporary(db_session, inactive_user)

    assert inactive_user.must_change_password is False


def test_set_new_password_after_temporary_clears_flag(
    db_session: Session, operario_user: User
) -> None:
    """EARS-H4-03"""
    temporary = reset_password_to_temporary(db_session, operario_user)

    set_new_password_after_temporary(
        db_session, operario_user, new_password="permanent-pass"
    )

    assert verify_password("permanent-pass", operario_user.password_hash)
    assert not verify_password(temporary, operario_user.password_hash)
    assert operario_user.must_change_password is False


def test_set_new_password_after_temporary_rejects_weak_password(
    db_session: Session, operario_user: User
) -> None:
    """EARS-H4-04"""
    temporary = reset_password_to_temporary(db_session, operario_user)

    with pytest.raises(WeakPasswordError):
        set_new_password_after_temporary(
            db_session, operario_user, new_password="short"
        )

    assert verify_password(temporary, operario_user.password_hash)
    assert operario_user.must_change_password is True
