from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def headers(user_id: str = "demo-user") -> dict[str, str]:
    return {"X-User-ID": user_id}


def test_health_and_openapi_31(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").json()["openapi"] == "3.1.0"


def test_memory_crud_is_scoped_to_user(client: TestClient) -> None:
    created = client.post(
        "/api/v1/memories",
        headers=headers(),
        json={"title": "Tercih", "content": "Türkçe yanıt"},
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]
    assert (
        client.get(f"/api/v1/memories/{memory_id}", headers=headers("other")).status_code
        == 404
    )
    assert client.patch(
        f"/api/v1/memories/{memory_id}", headers=headers(), json={}
    ).status_code == 422
    assert client.patch(
        f"/api/v1/memories/{memory_id}",
        headers=headers(),
        json={"title": None},
    ).status_code == 422
    updated = client.patch(
        f"/api/v1/memories/{memory_id}",
        headers=headers(),
        json={"content": "Kısa Türkçe yanıt"},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "Kısa Türkçe yanıt"
    assert client.delete(
        f"/api/v1/memories/{memory_id}", headers=headers()
    ).status_code == 204
    assert (
        client.get(f"/api/v1/memories/{memory_id}", headers=headers()).status_code
        == 404
    )


def test_chat_uses_demo_provider_without_external_credentials(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat/completions",
        headers=headers(),
        json={"messages": [{"role": "user", "content": "Merhaba"}]},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "demo"
    assert "Merhaba" in response.json()["reply"]


def test_capability_proposal_requires_explicit_decision(client: TestClient) -> None:
    proposal = client.post(
        "/api/v1/capability-proposals",
        headers=headers(),
        json={"name": "Yeni rapor", "description": "Özet rapor oluşturma"},
    )
    assert proposal.status_code == 201
    proposal_id = proposal.json()["id"]
    assert proposal.json()["status"] == "pending_approval"
    decided = client.post(
        f"/api/v1/capability-proposals/{proposal_id}/decision",
        headers=headers(),
        json={"decision": "approved"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    assert client.post(
        f"/api/v1/capability-proposals/{proposal_id}/decision",
        headers=headers(),
        json={"decision": "rejected"},
    ).status_code == 409


def test_orders_validate_products_and_do_not_process_payments(client: TestClient) -> None:
    response = client.post(
        "/api/v1/orders",
        headers=headers(),
        json={"items": [{"product_id": "starter-kit", "quantity": 2}]},
    )
    assert response.status_code == 201
    assert response.json()["total"] == 39.8
    assert response.json()["status"] == "pending"
    assert client.post(
        "/api/v1/orders",
        headers=headers(),
        json={"items": [{"product_id": "missing", "quantity": 1}]},
    ).status_code == 422


def test_appointments_require_timezone_and_reject_overlaps(client: TestClient) -> None:
    appointment = {
        "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "provider_name": "Demo sağlayıcı",
        "reason": "Demo randevu",
        "duration_minutes": 30,
    }
    created = client.post(
        "/api/v1/appointments", headers=headers(), json=appointment
    )
    assert created.status_code == 201
    assert client.post(
        "/api/v1/appointments", headers=headers(), json=appointment
    ).status_code == 409
    appointment["scheduled_at"] = "2030-01-01T10:00:00"
    assert client.post(
        "/api/v1/appointments", headers=headers(), json=appointment
    ).status_code == 422


def test_code_experiment_is_metadata_only_and_rejects_code_field(
    client: TestClient,
) -> None:
    queued = client.post(
        "/api/v1/code-experiments",
        headers=headers(),
        json={"title": "Deney", "description": "Açıklama metaverisi"},
    )
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"
    assert client.post(
        "/api/v1/code-experiments",
        headers=headers(),
        json={"title": "Deney", "description": "Açıklama", "code": "print('x')"},
    ).status_code == 422


def test_user_scoped_endpoint_requires_valid_user_header(client: TestClient) -> None:
    assert client.get("/api/v1/memories").status_code == 422
    assert (
        client.get("/api/v1/memories", headers={"X-User-ID": "bad user"}).status_code
        == 422
    )
