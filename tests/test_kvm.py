from pathlib import Path
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app.engine.kvm import kvm_is_available, run_bios_probe, run_kvm_smoke_test
from app.main import create_app

SEABIOS_PATH = Path("/usr/share/seabios/bios-256k.bin")
MINIMAL_ISO_PATH = Path(__file__).parent / "fixtures" / "minimal-linux.iso"


@pytest.mark.skipif(not kvm_is_available(), reason="KVM is unavailable")
def test_kvm_vcpu_runs_bounded_64_bit_guest_and_serial() -> None:
    result = run_kvm_smoke_test()

    assert result.eax == 42
    assert result.mode == "x86_64 long mode"
    assert result.serial_output == "W"
    assert result.halted is True
    assert result.instructions <= 16


@pytest.mark.skipif(
    not kvm_is_available() or not SEABIOS_PATH.is_file(),
    reason="KVM or SeaBIOS is unavailable",
)
def test_seabios_starts_on_direct_kvm_vm() -> None:
    result = run_bios_probe(
        SEABIOS_PATH,
        memory_size=256 << 20,
        max_exits=5000,
        timeout_seconds=10,
    )

    assert result.debug_output.startswith("SeaBIOS (version"), result.debug_output
    # This exit budget lands in early boot; reject the former ROM-shadow loop.
    assert result.instruction_bytes[:2] != b"\xf3\xa4", (
        result.terminal_reason,
        result.exits,
        result.debug_output,
        result.rip,
        result.instruction_bytes,
    )


@pytest.mark.skipif(
    not kvm_is_available()
    or not SEABIOS_PATH.is_file()
    or not MINIMAL_ISO_PATH.is_file(),
    reason="KVM, SeaBIOS or the local boot ISO is unavailable",
)
def test_seabios_reaches_local_iso_boot_device() -> None:
    result = run_bios_probe(
        SEABIOS_PATH,
        iso_path=str(MINIMAL_ISO_PATH),
        memory_size=256 << 20,
        max_exits=50_000,
        timeout_seconds=15,
    )

    port_counts = Counter(port for _, port, _, _ in result.io_trace)
    assert "qemu/e820" in result.debug_output or result.atapi_commands, (
        result.debug_output,
        result.terminal_reason,
        result.atapi_commands,
        sorted(port_counts.items()),
        result.io_trace[-100:],
    )


def test_kvm_smoke_endpoint_reports_host_capability() -> None:
    response = TestClient(create_app()).post("/api/v1/engine/kvm-smoke")

    if kvm_is_available():
        assert response.status_code == 200
        assert response.json()["eax"] == 42
        assert response.json()["mode"] == "x86_64 long mode"
        assert response.json()["serial_output"] == "W"
        assert response.json()["engine"] == "Wox KVM vCPU"
    else:
        assert response.status_code == 503
