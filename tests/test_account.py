from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import User


def test_new_users_do_not_require_password_change(operario_user: User) -> None:
    assert operario_user.must_change_password is False


def test_pending_password_change_redirects_any_route_to_set_password(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H4-02 (redirect wiring; end-to-end flow is covered in task 4)."""
    operario_user.must_change_password = True
    db_session.commit()

    for path in ("/", "/materials", "/movements"):
        response = operario_client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/account/set-password"
