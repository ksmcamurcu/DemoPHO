from pathlib import Path
import struct

import pytest

from app.engine.core import EngineError
from app.engine.devices import (
    ATA_CONTROL_PORT,
    ATA_DATA_PORT,
    ATA_LBA_HIGH_PORT,
    ATA_LBA_MID_PORT,
    ATA_STATUS_COMMAND_PORT,
    ATAPI_IDENTIFY_PACKET_COMMAND,
    ATAPI_PACKET_COMMAND,
    ISO_BLOCK_SIZE,
    AtapiCdrom,
    KvmIoBus,
    PcCmos,
    ReadOnlyIsoDevice,
)


def create_test_iso(path: Path, blocks: int = 18) -> bytes:
    content = bytearray(blocks * ISO_BLOCK_SIZE)
    content[16 * ISO_BLOCK_SIZE : 17 * ISO_BLOCK_SIZE] = (
        b"\x01CD001\x01" + b"\0" * (ISO_BLOCK_SIZE - 7)
    )
    content[17 * ISO_BLOCK_SIZE :] = b"x" * ISO_BLOCK_SIZE
    path.write_bytes(content)
    return bytes(content)


def send_atapi_packet(device: AtapiCdrom, packet: bytes) -> None:
    assert len(packet) == 12
    device.write_port(ATA_STATUS_COMMAND_PORT, bytes((ATAPI_PACKET_COMMAND,)))
    for offset in range(0, 12, 2):
        device.write_port(ATA_DATA_PORT, packet[offset : offset + 2])


def read_atapi_data(device: AtapiCdrom, byte_count: int) -> bytes:
    return b"".join(device.read_port(ATA_DATA_PORT, 2) for _ in range(byte_count // 2))


def test_read_only_iso_device_reads_bounded_sectors(tmp_path: Path) -> None:
    image = tmp_path / "demo.iso"
    content = create_test_iso(image)

    with ReadOnlyIsoDevice(image) as device:
        assert device.block_count == 18
        assert device.read_blocks(17, 1) == content[17 * ISO_BLOCK_SIZE :]

        with pytest.raises(EngineError, match="sınırlarının dışında"):
            device.read_blocks(18, 1)
        with pytest.raises(EngineError, match="1 ile"):
            device.read_blocks(0, 257)

    assert image.read_bytes() == content


def test_read_only_iso_device_rejects_non_iso_image(tmp_path: Path) -> None:
    image = tmp_path / "not-iso.iso"
    image.write_bytes(b"\0" * (18 * ISO_BLOCK_SIZE))

    with pytest.raises(EngineError, match="ISO 9660"):
        ReadOnlyIsoDevice(image)


def test_read_only_iso_device_rejects_truncated_image(tmp_path: Path) -> None:
    image = tmp_path / "short.iso"
    image.write_bytes(b"\0" * (16 * ISO_BLOCK_SIZE))

    with pytest.raises(EngineError, match="tanımlayıcısı"):
        ReadOnlyIsoDevice(image)


def test_atapi_cdrom_identifies_and_reads_iso_blocks(tmp_path: Path) -> None:
    image = tmp_path / "demo.iso"
    content = create_test_iso(image)

    with ReadOnlyIsoDevice(image) as iso:
        device = AtapiCdrom(iso)
        device.write_port(
            ATA_STATUS_COMMAND_PORT, bytes((ATAPI_IDENTIFY_PACKET_COMMAND,))
        )
        identity = read_atapi_data(device, 512)
        assert identity[:2] == b"\x80\x85"

        packet = bytearray(12)
        packet[0] = 0x28
        packet[2:6] = (17).to_bytes(4, "big")
        packet[7:9] = (1).to_bytes(2, "big")
        send_atapi_packet(device, bytes(packet))

        assert read_atapi_data(device, ISO_BLOCK_SIZE) == content[
            17 * ISO_BLOCK_SIZE :
        ]


def test_atapi_cdrom_exposes_packet_device_signature_after_reset(
    tmp_path: Path,
) -> None:
    image = tmp_path / "demo.iso"
    create_test_iso(image)

    with ReadOnlyIsoDevice(image) as iso:
        device = AtapiCdrom(iso)
        device.write_port(ATA_CONTROL_PORT, b"\x04")
        device.write_port(ATA_CONTROL_PORT, b"\0")

        assert device.read_port(ATA_LBA_MID_PORT, 1) == b"\x14"
        assert device.read_port(ATA_LBA_HIGH_PORT, 1) == b"\xeb"


def test_atapi_cdrom_reports_out_of_range_lba(tmp_path: Path) -> None:
    image = tmp_path / "demo.iso"
    create_test_iso(image)

    with ReadOnlyIsoDevice(image) as iso:
        device = AtapiCdrom(iso)
        packet = bytearray(12)
        packet[0] = 0x28
        packet[2:6] = (18).to_bytes(4, "big")
        packet[7:9] = (1).to_bytes(2, "big")
        send_atapi_packet(device, bytes(packet))
        assert device.status == 0x51

        sense = bytearray(12)
        sense[0] = 0x03
        sense[4] = 18
        send_atapi_packet(device, bytes(sense))
        response = read_atapi_data(device, 18)
        assert response[2] == 0x05
        assert response[12] == 0x21


def test_atapi_cdrom_reports_toc_tracks_and_lead_out(tmp_path: Path) -> None:
    image = tmp_path / "demo.iso"
    create_test_iso(image)

    with ReadOnlyIsoDevice(image) as iso:
        device = AtapiCdrom(iso)
        packet = bytearray(12)
        packet[0] = 0x43
        packet[7:9] = (20).to_bytes(2, "big")
        send_atapi_packet(device, bytes(packet))
        toc = read_atapi_data(device, 20)

        assert toc[0:4] == b"\x00\x12\x01\x01"
        assert toc[5:7] == b"\x14\x01"
        assert toc[13:15] == b"\x14\xaa"
        assert toc[16:20] == (18).to_bytes(4, "big")


def test_atapi_cdrom_returns_a_bounded_mode_sense_header(tmp_path: Path) -> None:
    image = tmp_path / "demo.iso"
    create_test_iso(image)

    with ReadOnlyIsoDevice(image) as iso:
        device = AtapiCdrom(iso)
        packet = bytearray(12)
        packet[0] = 0x1A
        packet[4] = 4
        send_atapi_packet(device, bytes(packet))

        assert read_atapi_data(device, 4) == b"\x03\0\0\0"


def test_kvm_io_bus_emulates_serial_without_iso(tmp_path: Path) -> None:
    bus = KvmIoBus()

    bus.write(0x3F8, b"W")

    assert bus.serial_output == ["W"]
    with pytest.raises(EngineError, match="Desteklenmeyen"):
        bus.read(0x1F0, 2)


def test_pc_cmos_reports_memory_and_cdrom_boot_order() -> None:
    cmos = PcCmos(64 << 20)

    assert cmos.registers[0x15:0x17] == (640).to_bytes(2, "little")
    assert cmos.registers[0x17:0x19] == (15 * 1024).to_bytes(2, "little")
    assert cmos.registers[0x30:0x32] == (63 * 1024).to_bytes(2, "little")
    assert cmos.registers[0x34:0x36] == (768).to_bytes(2, "little")
    assert cmos.registers[0x3D] == 0x23


def test_cmos_memory_registers_are_selected_through_io_bus() -> None:
    bus = KvmIoBus(memory_size=64 << 20)

    bus.write(0x70, b"\xB5")

    assert bus.read(0x71, 1) == b"\x03"
    assert bus.io_trace[-1] == ("in", 0x71, 1, b"\x03")


def test_firmware_config_exposes_e820_memory_map() -> None:
    memory_size = 64 << 20
    bus = KvmIoBus(memory_size=memory_size)

    bus.write(0x510, b"\0\0")
    assert bus.read(0x511, 4) == b"QEMU"

    bus.write(0x510, b"\x19\0")
    assert bus.read(0x511, 4) == b"\0\0\0\1"
    directory_entry = bus.read(0x511, 64)
    assert directory_entry == struct.pack(
        ">IHH56s", 60, 0x20, 0, b"etc/e820"
    )

    bus.write(0x510, b"\x20\0")
    expected_map = b"".join(
        struct.pack("<QQI", start, size, kind)
        for start, size, kind in (
            (0, 0xA0000, 1),
            (0xA0000, 0x60000, 2),
            (1 << 20, memory_size - (1 << 20), 1),
        )
    )
    assert bus.read(0x511, 60) == expected_map


def test_i440fx_bridge_identity_is_visible_through_pci_config() -> None:
    bus = KvmIoBus(memory_size=64 << 20)

    bus.write(0xCF8, (0x80000000).to_bytes(4, "little"))

    assert bus.read(0xCFC, 4) == (0x12378086).to_bytes(4, "little")
    assert bus.read(0xCFC, 2) == (0x8086).to_bytes(2, "little")

    bus.write(0xCF8, (0x8000002C).to_bytes(4, "little"))
    assert bus.read(0xCFC, 4) == (0x11001AF4).to_bytes(4, "little")


def test_pc_pit_channel_two_drives_speaker_status(monkeypatch) -> None:
    clock = [0]
    monkeypatch.setattr("app.engine.devices.monotonic_ns", lambda: clock[0])
    bus = KvmIoBus(ignore_unknown=True)
    bus.write(0x43, b"\xB0")
    bus.write(0x42, b"\xA9")
    bus.write(0x42, b"\x04")
    bus.write(0x61, b"\x01")

    assert bus.read(0x61, 1)[0] & 0x20 == 0
    clock[0] = 1_000_000

    assert bus.read(0x61, 1)[0] & 0x20 == 0x20
