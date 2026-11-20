import pytest
from fastapi.testclient import TestClient

from app.engine.core import EngineError, run_program
from app.main import create_app
from app.schemas import WoxInstruction


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health_and_openapi_31(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "engine": "Wox Core"}
    assert client.get("/openapi.json").json()["openapi"] == "3.1.0"


def test_engine_reports_host_isolation_and_planned_guests(client: TestClient) -> None:
    info = client.get("/api/v1/engine").json()
    assert info["name"] == "Wox Core"
    assert info["host_access"] is False
    assert info["guest_os_boot"] is False
    assert "Pardus ARM64" in info["planned_guest_systems"]


def test_custom_engine_runs_bounded_arithmetic_program(client: TestClient) -> None:
    response = client.post(
        "/api/v1/engine/run",
        json={
            "program": [
                {"op": "load_imm", "register": 0, "value": 7},
                {"op": "load_imm", "register": 1, "value": 35},
                {"op": "add", "register": 0, "source": 1},
                {"op": "print", "register": 0},
                {"op": "halt"},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["output"] == ["42"]
    assert response.json()["registers"] == [42, 35, 0, 0]
    assert response.json()["halted"] is True


def test_custom_engine_loads_and_stores_only_virtual_memory() -> None:
    result = run_program(
        [
            WoxInstruction(op="load_imm", register=0, value=1234),
            WoxInstruction(op="store", source=0, address=8),
            WoxInstruction(op="load_imm", register=0, value=0),
            WoxInstruction(op="load", register=1, address=8),
            WoxInstruction(op="print", register=1),
            WoxInstruction(op="halt"),
        ]
    )
    assert result.output == ["1234"]
    assert result.registers[1] == 1234


def test_engine_rejects_host_code_and_unrecognized_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/engine/run",
        json={
            "program": [
                {"op": "load_imm", "register": 0, "value": 1, "python": "print(1)"},
                {"op": "halt"},
            ]
        },
    )
    assert response.status_code == 422


def test_engine_rejects_missing_operands_and_out_of_bounds_memory(client: TestClient) -> None:
    missing_operand = client.post(
        "/api/v1/engine/run",
        json={"program": [{"op": "load_imm", "register": 0}, {"op": "halt"}]},
    )
    assert missing_operand.status_code == 422
    out_of_bounds = client.post(
        "/api/v1/engine/run",
        json={
            "program": [
                {"op": "load", "register": 0, "address": 65530},
                {"op": "halt"},
            ]
        },
    )
    assert out_of_bounds.status_code == 422


def test_engine_stops_at_instruction_limit() -> None:
    program = [
        WoxInstruction(op="jump", target=0),
    ]
    with pytest.raises(EngineError, match="işlem sınırını"):
        run_program(program)


def test_previous_demo_api_routes_are_removed(client: TestClient) -> None:
    assert client.get("/api/v1/memories", headers={"X-User-ID": "demo"}).status_code == 404
