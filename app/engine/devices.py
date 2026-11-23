from collections import deque
from pathlib import Path
import struct
from time import monotonic_ns

from app.engine.core import EngineError
from app.iso_manager import MAX_ISO_BYTES

ISO_BLOCK_SIZE = 2048
ISO_VOLUME_DESCRIPTOR_LBA = 16
MAX_READ_BLOCKS = 256
COM1_DATA_PORT = 0x3F8
COM1_LINE_STATUS_PORT = 0x3FD
DEBUG_CONSOLE_PORT = 0x0402
ATA_DATA_PORT = 0x1F0
ATA_ERROR_PORT = 0x1F1
ATA_SECTOR_COUNT_PORT = 0x1F2
ATA_LBA_LOW_PORT = 0x1F3
ATA_LBA_MID_PORT = 0x1F4
ATA_LBA_HIGH_PORT = 0x1F5
ATA_DRIVE_SELECT_PORT = 0x1F6
ATA_STATUS_COMMAND_PORT = 0x1F7
ATA_CONTROL_PORT = 0x3F6
ATA_PORTS = {*range(ATA_DATA_PORT, ATA_STATUS_COMMAND_PORT + 1), ATA_CONTROL_PORT}
CMOS_INDEX_PORT = 0x70
CMOS_DATA_PORT = 0x71
KEYBOARD_DATA_PORT = 0x60
KEYBOARD_STATUS_PORT = 0x64
PCI_CONFIG_ADDRESS_PORT = 0xCF8
PCI_CONFIG_DATA_START = 0xCFC
PCI_CONFIG_DATA_END = 0xCFF
ATAPI_PACKET_COMMAND = 0xA0
ATAPI_IDENTIFY_PACKET_COMMAND = 0xA1
ATAPI_MAX_TRANSFER = 32 * 1024
PIT_CHANNEL_2_PORT = 0x42
PIT_COMMAND_PORT = 0x43
PIT_INPUT_HZ = 1_193_182
FW_CFG_SELECTOR_PORT = 0x510
FW_CFG_DATA_PORT = 0x511
FW_CFG_SIGNATURE = 0x00
FW_CFG_ID = 0x01
FW_CFG_FILE_DIR = 0x19
FW_CFG_E820_FILE = 0x20
E820_RAM = 1
E820_RESERVED = 2


class ReadOnlyIsoDevice:
    def __init__(self, path: str | Path) -> None:
        image_path = Path(path).expanduser().resolve(strict=True)
        if not image_path.is_file():
            raise EngineError("Konuk CD imajı normal bir dosya olmalıdır.")

        self._file = image_path.open("rb")
        try:
            size = image_path.stat().st_size
            if size < (ISO_VOLUME_DESCRIPTOR_LBA + 1) * ISO_BLOCK_SIZE:
                raise EngineError("ISO imajı birincil birim tanımlayıcısı içermiyor.")
            if size > MAX_ISO_BYTES or size % ISO_BLOCK_SIZE:
                raise EngineError("ISO boyutu geçerli sınırların dışında.")

            self.size_bytes = size
            self.block_count = size // ISO_BLOCK_SIZE
            descriptor = self.read_blocks(ISO_VOLUME_DESCRIPTOR_LBA, 1)
            if descriptor[0] != 1 or descriptor[1:6] != b"CD001" or descriptor[6] != 1:
                raise EngineError("Dosya geçerli bir ISO 9660 imajı değil.")
        except (EngineError, OSError):
            self._file.close()
            raise

    def read_blocks(self, start: int, count: int) -> bytes:
        if count < 1 or count > MAX_READ_BLOCKS:
            raise EngineError(
                f"Bir istekte 1 ile {MAX_READ_BLOCKS} ISO bloğu okunabilir."
            )
        if start < 0 or start + count > self.block_count:
            raise EngineError("ISO blok isteği imaj sınırlarının dışında.")

        self._file.seek(start * ISO_BLOCK_SIZE)
        data = self._file.read(count * ISO_BLOCK_SIZE)
        if len(data) != count * ISO_BLOCK_SIZE:
            raise EngineError("ISO imajı beklenmedik biçimde kesildi.")
        return data

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "ReadOnlyIsoDevice":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class AtapiCdrom:
    def __init__(self, iso: ReadOnlyIsoDevice) -> None:
        self.iso = iso
        self.status = 0x50
        self.error = 0
        self.sector_count = 1
        self.lba_low = 1
        self.lba_mid = 0x14
        self.lba_high = 0xEB
        self.drive_select = 0xA0
        self.device_control = 0
        self._packet = bytearray()
        self._expecting_packet = False
        self._pending_data = b""
        self._data = b""
        self._data_offset = 0
        self._sense_key = 0
        self._sense_asc = 0
        self._sense_ascq = 0
        self.command_history: list[int] = []
        self.read_requests: list[tuple[int, int]] = []

    def write_port(self, port: int, data: bytes) -> None:
        if port == ATA_STATUS_COMMAND_PORT:
            if len(data) != 1:
                raise EngineError("ATAPI komut yazımı tek bayt olmalıdır.")
            command = data[0]
            if command == ATAPI_PACKET_COMMAND:
                self._packet.clear()
                self._expecting_packet = True
                self.status = 0x58
                self.sector_count = 1
            elif command == ATAPI_IDENTIFY_PACKET_COMMAND:
                self._expecting_packet = False
                self._begin_data(self._identify_packet_device())
            elif command == 0xEC:
                self._check_condition(0x04, 0x00)
            else:
                self._check_condition(0x05, 0x20)
            return

        if port == ATA_DRIVE_SELECT_PORT and len(data) == 1:
            self.drive_select = data[0]
            return
        if port == ATA_CONTROL_PORT and len(data) == 1:
            was_reset = bool(self.device_control & 0x04)
            self.device_control = data[0]
            is_reset = bool(self.device_control & 0x04)
            if is_reset:
                self.status = 0x80
            elif was_reset:
                self.reset()
            return

        if port == ATA_DATA_PORT and self._expecting_packet:
            self._packet.extend(data)
            if len(self._packet) >= 12:
                self._expecting_packet = False
                self._execute_packet(bytes(self._packet[:12]))
            return

        if port == ATA_ERROR_PORT and len(data) == 1:
            self.error = data[0]
            return
        if port == ATA_SECTOR_COUNT_PORT and len(data) == 1:
            self.sector_count = data[0]
            return
        if port == ATA_LBA_LOW_PORT and len(data) == 1:
            self.lba_low = data[0]
            return
        if port == ATA_LBA_MID_PORT and len(data) == 1:
            self.lba_mid = data[0]
            return
        if port == ATA_LBA_HIGH_PORT and len(data) == 1:
            self.lba_high = data[0]
            return
        raise EngineError(f"Desteklenmeyen konuk I/O portu: 0x{port:04x}.")

    def read_port(self, port: int, size: int) -> bytes:
        if size not in {1, 2, 4}:
            raise EngineError("Konuk I/O okuma boyutu 1, 2 veya 4 bayt olmalıdır.")
        if port == ATA_STATUS_COMMAND_PORT:
            return bytes((self.status,)) * size
        if port == ATA_CONTROL_PORT:
            return bytes((self.status,)) * size
        if port == ATA_DRIVE_SELECT_PORT:
            return bytes((self.drive_select,)) * size
        if port == ATA_ERROR_PORT:
            return bytes((self.error,)) * size
        if port == ATA_SECTOR_COUNT_PORT:
            return bytes((self.sector_count,)) * size
        if port == ATA_LBA_LOW_PORT:
            return bytes((self.lba_low,)) * size
        if port == ATA_LBA_MID_PORT:
            return bytes((self.lba_mid,)) * size
        if port == ATA_LBA_HIGH_PORT:
            return bytes((self.lba_high,)) * size
        if port == ATA_DATA_PORT:
            return self._read_data(size)
        raise EngineError(f"Desteklenmeyen konuk I/O portu: 0x{port:04x}.")

    def _execute_packet(self, packet: bytes) -> None:
        command = packet[0]
        self.command_history.append(command)
        if command == 0x00:
            self._begin_data(b"")
        elif command in {0x1B, 0x1E}:
            self._begin_data(b"")
        elif command == 0x03:
            self._request_sense(packet)
        elif command == 0x12:
            self._inquiry(packet)
        elif command == 0x25:
            self._read_capacity()
        elif command == 0x43:
            self._read_toc(packet)
        elif command in {0x1A, 0x5A}:
            self._mode_sense(packet)
        elif command == 0x28:
            self._read_10(packet)
        else:
            self._check_condition(0x05, 0x20)

    def reset(self) -> None:
        self.error = 1
        self.sector_count = 1
        self.lba_low = 1
        self.lba_mid = 0x14
        self.lba_high = 0xEB
        self.status = 0x50
        self._packet.clear()
        self._expecting_packet = False
        self._pending_data = self._data = b""
        self._data_offset = 0

    def _identify_packet_device(self) -> bytes:
        data = bytearray(512)
        words = {
            0: 0x8580,
            49: 0x0300,
            53: 0x0007,
            63: 0x0007,
            64: 0x0003,
            80: 0x001E,
        }
        for index, value in words.items():
            data[index * 2 : index * 2 + 2] = value.to_bytes(2, "little")
        self._put_ata_string(data, 10, 10, "WOX000000001")
        self._put_ata_string(data, 23, 4, "1.0")
        self._put_ata_string(data, 27, 20, "WOX VIRTUAL CD-ROM")
        return bytes(data)

    @staticmethod
    def _put_ata_string(
        data: bytearray, start_word: int, word_count: int, value: str
    ) -> None:
        encoded = value.encode("ascii")[: word_count * 2].ljust(word_count * 2)
        for index in range(0, len(encoded), 2):
            offset = start_word * 2 + index
            data[offset : offset + 2] = encoded[index : index + 2][::-1]

    def _inquiry(self, packet: bytes) -> None:
        data = bytearray(36)
        data[0] = 0x05
        data[1] = 0x80
        data[2] = 0x05
        data[3] = 0x02
        data[4] = 31
        data[8:16] = b"WOX     "
        data[16:32] = b"DEMO KEON CDROM "
        data[32:36] = b"0001"
        self._begin_data(bytes(data[: packet[4]]))

    def _read_capacity(self) -> None:
        last_lba = self.iso.block_count - 1
        self._begin_data(last_lba.to_bytes(4, "big") + ISO_BLOCK_SIZE.to_bytes(4, "big"))

    def _read_toc(self, packet: bytes) -> None:
        lead_out = self.iso.block_count
        data = bytearray(20)
        data[0:2] = (18).to_bytes(2, "big")
        data[2:4] = b"\x01\x01"
        data[5:8] = b"\x14\x01\x00"
        data[13:16] = b"\x14\xaa\x00"
        if packet[1] & 0x02:
            data[9:12] = self._lba_to_msf(0)
            data[17:20] = self._lba_to_msf(lead_out)
        else:
            data[8:12] = (0).to_bytes(4, "big")
            data[16:20] = lead_out.to_bytes(4, "big")
        self._begin_data(bytes(data[: int.from_bytes(packet[7:9], "big")]))

    @staticmethod
    def _lba_to_msf(lba: int) -> bytes:
        frames = lba + 150
        minutes, frames = divmod(frames, 75 * 60)
        seconds, frames = divmod(frames, 75)
        return bytes((minutes, seconds, frames))

    def _mode_sense(self, packet: bytes) -> None:
        if packet[0] == 0x1A:
            allocation_length = packet[4]
            data = bytes((3, 0, 0, 0))
        else:
            allocation_length = int.from_bytes(packet[7:9], "big")
            data = bytes((0, 6, 0, 0, 0, 0, 0, 0))
        self._begin_data(data[:allocation_length])

    def _read_10(self, packet: bytes) -> None:
        start = int.from_bytes(packet[2:6], "big")
        count = int.from_bytes(packet[7:9], "big")
        self.read_requests.append((start, count))
        if count == 0:
            self._begin_data(b"")
            return
        if count > MAX_READ_BLOCKS:
            self._check_condition(0x05, 0x24)
            return
        try:
            data = self.iso.read_blocks(start, count)
        except EngineError:
            self._check_condition(0x05, 0x21)
            return
        self._begin_data(data)

    def _request_sense(self, packet: bytes) -> None:
        data = bytearray(18)
        data[0] = 0x70
        data[2] = self._sense_key
        data[7] = 10
        data[12] = self._sense_asc
        data[13] = self._sense_ascq
        self._sense_key = self._sense_asc = self._sense_ascq = 0
        self._begin_data(bytes(data[: packet[4]]))

    def _check_condition(self, sense_key: int, asc: int) -> None:
        self._sense_key = sense_key
        self._sense_asc = asc
        self._sense_ascq = 0
        self.error = sense_key << 4
        self.sector_count = 3
        self.status = 0x51
        self._pending_data = self._data = b""
        self._data_offset = 0

    def _begin_data(self, data: bytes) -> None:
        self._pending_data = data + (b"\0" if len(data) % 2 else b"")
        self._next_data_phase()

    def _next_data_phase(self) -> None:
        if not self._pending_data:
            self._data = b""
            self._data_offset = 0
            self.lba_mid = self.lba_high = 0
            self.sector_count = 0
            self.status = 0x50
            return

        transfer_size = min(len(self._pending_data), ATAPI_MAX_TRANSFER)
        transfer_size &= ~1
        self._data = self._pending_data[:transfer_size]
        self._pending_data = self._pending_data[transfer_size:]
        self._data_offset = 0
        self.lba_mid = transfer_size & 0xFF
        self.lba_high = (transfer_size >> 8) & 0xFF
        self.sector_count = 2
        self.status = 0x58

    def _read_data(self, size: int) -> bytes:
        if not self._data:
            return bytes(size)
        end = min(self._data_offset + size, len(self._data))
        data = self._data[self._data_offset : end]
        self._data_offset = end
        if self._data_offset >= len(self._data):
            self._next_data_phase()
        return data.ljust(size, b"\0")


class PcCmos:
    def __init__(self, memory_size: int) -> None:
        memory_kib = memory_size // 1024
        self.index = 0
        self.registers = bytearray(128)
        self.registers[0x0A] = 0x26
        self.registers[0x0B] = 0x02
        self.registers[0x0D] = 0x80
        self.registers[0x14] = 0x2D
        self.registers[0x15:0x17] = (640).to_bytes(2, "little")
        below_16m_kib = min(max(memory_kib - 1024, 0), 15 * 1024)
        self.registers[0x17:0x19] = below_16m_kib.to_bytes(2, "little")
        extended_memory_kib = min(max(memory_kib - 1024, 0), 0xFFFF)
        self.registers[0x30:0x32] = extended_memory_kib.to_bytes(2, "little")
        above_16m_blocks = max(memory_size // (64 * 1024) - 256, 0)
        self.registers[0x34:0x36] = min(above_16m_blocks, 0xFFFF).to_bytes(
            2, "little"
        )
        self.registers[0x3D] = 0x23
        self.registers[0x3E] = 0x00

    def read(self) -> int:
        return self.registers[self.index & 0x7F]

    def write(self, value: int) -> None:
        self.registers[self.index & 0x7F] = value


class FirmwareConfig:
    def __init__(self, memory_size: int) -> None:
        low_ram_end = 0xA0000
        high_ram_start = 1 << 20
        e820 = b"".join(
            struct.pack("<QQI", start, size, kind)
            for start, size, kind in (
                (0, low_ram_end, E820_RAM),
                (low_ram_end, high_ram_start - low_ram_end, E820_RESERVED),
                (
                    high_ram_start,
                    memory_size - high_ram_start,
                    E820_RAM,
                ),
            )
        )
        name = b"etc/e820"
        directory = struct.pack(">I", 1) + struct.pack(
            ">IHH56s", len(e820), FW_CFG_E820_FILE, 0, name
        )
        self._files = {
            FW_CFG_SIGNATURE: b"QEMU",
            FW_CFG_ID: b"\0\0\0\0",
            FW_CFG_FILE_DIR: directory,
            FW_CFG_E820_FILE: e820,
        }
        self._selector = FW_CFG_SIGNATURE
        self._offset = 0

    def select(self, data: bytes) -> None:
        if len(data) != 2:
            raise EngineError("Firmware-config seçimi iki bayt olmalıdır.")
        self._selector = int.from_bytes(data, "little")
        self._offset = 0

    def read(self, size: int) -> bytes:
        data = self._files.get(self._selector, b"")
        result = data[self._offset : self._offset + size].ljust(size, b"\0")
        self._offset += size
        return result


class PitChannel2:
    def __init__(self) -> None:
        self.reload = 0x10000
        self.mode = 3
        self.access_mode = 3
        self._write_low: int | None = None
        self._gate = False
        self._started_at = monotonic_ns()
        self._output = True

    def write_command(self, command: int) -> None:
        if ((command >> 6) & 0x03) != 2:
            return
        access_mode = (command >> 4) & 0x03
        if access_mode == 0:
            return
        mode = (command >> 1) & 0x07
        self.access_mode = access_mode
        self.mode = mode - 4 if mode in {6, 7} else mode
        self._write_low = None
        self._output = self.mode != 0

    def write_count(self, value: int) -> None:
        if self.access_mode == 1:
            self._set_reload(value)
        elif self.access_mode == 2:
            self._set_reload(value << 8)
        elif self._write_low is None:
            self._write_low = value
        else:
            self._set_reload(self._write_low | (value << 8))
            self._write_low = None

    def set_gate(self, enabled: bool) -> None:
        if enabled and not self._gate:
            self._started_at = monotonic_ns()
        self._gate = enabled

    def output(self) -> bool:
        if not self._gate or self.mode not in {0, 2, 3}:
            return self._output
        elapsed_ticks = (
            (monotonic_ns() - self._started_at) * PIT_INPUT_HZ // 1_000_000_000
        )
        if self.mode == 0:
            self._output = elapsed_ticks >= self.reload
            return self._output
        if self.mode == 2:
            return elapsed_ticks % self.reload != self.reload - 1
        return (elapsed_ticks % self.reload) < (self.reload + 1) // 2

    def _set_reload(self, value: int) -> None:
        self.reload = value or 0x10000
        self._started_at = monotonic_ns()
        self._output = self.mode != 0


class KvmIoBus:
    def __init__(
        self,
        iso: ReadOnlyIsoDevice | None = None,
        *,
        ignore_unknown: bool = False,
        memory_size: int = 64 << 20,
    ) -> None:
        self.serial_output: list[str] = []
        self.debug_output: list[str] = []
        self.cdrom = AtapiCdrom(iso) if iso is not None else None
        self.ignore_unknown = ignore_unknown
        self.cmos = PcCmos(memory_size)
        self.firmware_config = FirmwareConfig(memory_size)
        self.pit_channel2 = PitChannel2()
        self._serial_registers = bytearray(8)
        self._keyboard_response = bytearray()
        self._keyboard_status = 0
        self._keyboard_command_byte = 0x01
        self._pci_config_address = 0
        self._pci_config_registers: dict[int, int] = {
            0x00: 0x12378086,
            0x08: 0x02000002,
            0x2C: 0x11001AF4,
            0x59: 0x00,
        }
        self._vga_registers: dict[int, int] = {}
        self._speaker_control = 0
        self._speaker_timer_output = 0
        self._system_control = 0x02
        self.io_trace: deque[tuple[str, int, int, bytes]] = deque(maxlen=2048)

    def write(self, port: int, data: bytes) -> None:
        if port not in {ATA_DATA_PORT, DEBUG_CONSOLE_PORT}:
            self.io_trace.append(("out", port, len(data), data))
        if not data:
            return
        if port == DEBUG_CONSOLE_PORT:
            self.debug_output.extend(chr(value) for value in data)
        elif COM1_DATA_PORT <= port <= COM1_DATA_PORT + 7:
            offset = port - COM1_DATA_PORT
            for value in data:
                if offset == 0 and not self._serial_registers[3] & 0x80:
                    self.serial_output.append(chr(value))
                else:
                    self._serial_registers[offset] = value
        elif port in ATA_PORTS and self.cdrom is not None:
            self.cdrom.write_port(port, data)
        elif port == CMOS_INDEX_PORT:
            self.cmos.index = data[-1] & 0x7F
        elif port == CMOS_DATA_PORT:
            self.cmos.write(data[-1])
        elif port == FW_CFG_SELECTOR_PORT:
            self.firmware_config.select(data)
        elif port == KEYBOARD_STATUS_PORT:
            self._write_keyboard_command(data[-1])
        elif port == KEYBOARD_DATA_PORT:
            self._write_keyboard_data(data[-1])
        elif port == PCI_CONFIG_ADDRESS_PORT:
            self._pci_config_address = int.from_bytes(data[:4].ljust(4, b"\0"), "little")
        elif PCI_CONFIG_DATA_START <= port <= PCI_CONFIG_DATA_END:
            if self._pci_config_address & 0x80000000:
                bus = (self._pci_config_address >> 16) & 0xFF
                device_function = (self._pci_config_address >> 8) & 0xFF
                if bus == 0 and device_function == 0:
                    register = (self._pci_config_address & 0xFC) + (port - PCI_CONFIG_DATA_START)
                    value = int.from_bytes(data, "little")
                    shift = (register & 3) * 8
                    old = self._pci_config_registers.get(register & ~3, 0)
                    mask = ((1 << (len(data) * 8)) - 1) << shift
                    self._pci_config_registers[register & ~3] = (
                        old & ~mask
                    ) | ((value & ((1 << (len(data) * 8)) - 1)) << shift)
        elif port == 0x61:
            self._speaker_control = data[-1]
            self.pit_channel2.set_gate(bool(data[-1] & 0x01))
        elif port == PIT_COMMAND_PORT:
            self.pit_channel2.write_command(data[-1])
        elif port == PIT_CHANNEL_2_PORT:
            self.pit_channel2.write_count(data[-1])
        elif port == 0x92:
            self._system_control = data[-1] | 0x02
        elif 0x3B0 <= port <= 0x3DF:
            self._vga_registers[port] = data[-1]
        elif self.ignore_unknown:
            return
        else:
            raise EngineError(f"Desteklenmeyen konuk I/O portu: 0x{port:04x}.")

    def read(self, port: int, size: int) -> bytes:
        if port != ATA_DATA_PORT:
            self.io_trace.append(("in", port, size, b""))
        if COM1_DATA_PORT <= port <= COM1_DATA_PORT + 7:
            offset = port - COM1_DATA_PORT
            if offset == 5:
                value = 0x60
            elif offset == 6:
                value = 0xB0
            else:
                value = self._serial_registers[offset]
            return bytes((value,)) * size
        if port in ATA_PORTS and self.cdrom is not None:
            return self.cdrom.read_port(port, size)
        if port == CMOS_INDEX_PORT:
            return bytes((self.cmos.index,)) * size
        if port == CMOS_DATA_PORT:
            data = bytes((self.cmos.read(),)) * size
            self.io_trace[-1] = ("in", port, size, data)
            return data
        if port == FW_CFG_DATA_PORT:
            data = self.firmware_config.read(size)
            self.io_trace[-1] = ("in", port, size, data)
            return data
        if port == KEYBOARD_STATUS_PORT:
            return bytes((self._keyboard_status,)) * size
        if port == KEYBOARD_DATA_PORT:
            values = bytes(self._keyboard_response[:size]).ljust(size, b"\0")
            del self._keyboard_response[:size]
            self._keyboard_status = int(bool(self._keyboard_response))
            return values
        if PCI_CONFIG_DATA_START <= port <= PCI_CONFIG_DATA_END:
            if self._pci_config_address & 0x80000000:
                bus = (self._pci_config_address >> 16) & 0xFF
                device_function = (self._pci_config_address >> 8) & 0xFF
                if bus == 0 and device_function == 0:
                    base = self._pci_config_address & 0xFC
                    offset = port - PCI_CONFIG_DATA_START
                    register = base + offset
                    value = 0
                    for index in range(size):
                        register_index = register + index
                        base_index = register_index & ~3
                        shift = (register_index & 3) * 8
                        value |= (
                            (self._pci_config_registers.get(base_index, 0) >> shift)
                            & 0xFF
                        ) << (index * 8)
                    return value.to_bytes(size, "little")
            return bytes((0xFF,)) * size
        if port == 0x61:
            timer_output = 0x20 if self.pit_channel2.output() else 0
            value = (self._speaker_control & ~0x20) | timer_output
            return bytes((value,)) * size
        if port == 0x92:
            return bytes((self._system_control,)) * size
        if 0x3B0 <= port <= 0x3DF:
            value = 0x08 if port == 0x3DA else self._vga_registers.get(port, 0)
            return bytes((value,)) * size
        if self.ignore_unknown:
            return bytes(size)
        raise EngineError(f"Desteklenmeyen konuk I/O portu: 0x{port:04x}.")

    def _write_keyboard_command(self, command: int) -> None:
        if command == 0x20:
            self._keyboard_response.extend((self._keyboard_command_byte,))
        elif command == 0xAA:
            self._keyboard_response.extend((0x55,))
        elif command == 0xAB:
            self._keyboard_response.extend((0x00,))
        elif command == 0x60:
            self._keyboard_status |= 0x02
        self._keyboard_status = int(bool(self._keyboard_response)) | (
            self._keyboard_status & 0x02
        )

    def _write_keyboard_data(self, value: int) -> None:
        if self._keyboard_status & 0x02:
            self._keyboard_command_byte = value
            self._keyboard_status &= ~0x02
        elif value == 0xFF:
            self._keyboard_response.extend((0xFA, 0xAA))
        elif value == 0xF2:
            self._keyboard_response.extend((0xFA, 0xAB, 0x83))
        elif value in {
            0xED,
            0xF3,
            0xF4,
            0xF5,
            0xF6,
            0xF7,
            0xF8,
            0xF9,
            0xFA,
            0xFB,
            0xFC,
            0xFD,
            0xFE,
        }:
            self._keyboard_response.extend((0xFA,))
        self._keyboard_status = int(bool(self._keyboard_response))
