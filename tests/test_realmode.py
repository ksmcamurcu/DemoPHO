import pytest
from fastapi.testclient import TestClient

from app.engine.core import EngineError
from app.engine.realmode import (
    MAX_BOOT_STEPS,
    SAMPLE_BOOT_SECTOR,
    run_boot_sector,
)
from app.main import create_app


def test_x86_real_mode_executes_a_bios_text_boot_sector() -> None:
    result = run_boot_sector(SAMPLE_BOOT_SECTOR)

    assert result.output == "WOX 16-bit boot sector!"
    assert result.instructions < MAX_BOOT_STEPS


def test_x86_real_mode_rejects_bad_sector_size_or_signature() -> None:
    with pytest.raises(EngineError, match="512 bayt"):
        run_boot_sector(b"\0" * 511)
    with pytest.raises(EngineError, match="imza"):
        run_boot_sector(b"\0" * 512)


def test_x86_real_mode_rejects_unsupported_disk_bios_interrupt() -> None:
    sector = bytearray(512)
    sector[:4] = b"\xb4\x02\xcd\x13"
    sector[510:] = b"\x55\xaa"

    with pytest.raises(EngineError, match="BIOS kesmesi 0x13"):
        run_boot_sector(bytes(sector))


def test_x86_real_mode_enforces_instruction_limit() -> None:
    sector = bytearray(512)
    sector[:2] = b"\xeb\xfe"
    sector[510:] = b"\x55\xaa"

    with pytest.raises(EngineError, match="adım sınırını"):
        run_boot_sector(bytes(sector))


def test_boot_sector_api_returns_emulated_text() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/engine/boot-sector",
        json={"boot_sector_hex": SAMPLE_BOOT_SECTOR.hex()},
    )

    assert response.status_code == 200
    assert response.json()["engine"] == "Wox x86 Real Mode"
    assert response.json()["output"] == "WOX 16-bit boot sector!"


def test_boot_sector_api_rejects_invalid_signature() -> None:
    client = TestClient(create_app())
    invalid_sector = bytearray(SAMPLE_BOOT_SECTOR)
    invalid_sector[511] = 0

    response = client.post(
        "/api/v1/engine/boot-sector",
        json={"boot_sector_hex": invalid_sector.hex()},
    )

    assert response.status_code == 422
