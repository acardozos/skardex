from fastapi.testclient import TestClient


def test_unknown_route_returns_friendly_html_not_json(client: TestClient) -> None:
    response = client.get("/this-route-does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "not found" not in response.text.lower()


def test_forbidden_route_returns_friendly_html_not_json(
    operario_client: TestClient,
) -> None:
    response = operario_client.get("/materials/new")

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("text/html")
