from dataclasses import dataclass

from app.engine.core import EngineError

MEMORY_SIZE = 1 << 20
BOOT_ADDRESS = 0x7C00
BOOT_SECTOR_SIZE = 512
MAX_BOOT_STEPS = 100_000
MAX_BOOT_OUTPUT = 4096

CF = 0x0001
ZF = 0x0040
SF = 0x0080
OF = 0x0800


@dataclass(frozen=True)
class BootResult:
    output: str
    instructions: int


def build_sample_boot_sector() -> bytes:
    code = bytes(
        (
            0xBE,
            0x10,
            0x7C,  # mov si, 0x7c10
            0xAC,  # lodsb
            0x84,
            0xC0,  # test al, al
            0x74,
            0x06,  # jz halt
            0xB4,
            0x0E,  # mov ah, 0x0e
            0xCD,
            0x10,  # int 0x10
            0xEB,
            0xF5,  # jmp lodsb
            0xF4,  # hlt
            0x90,
        )
    ) + b"WOX 16-bit boot sector!\0"
    return code.ljust(BOOT_SECTOR_SIZE - 2, b"\0") + b"\x55\xaa"


SAMPLE_BOOT_SECTOR = build_sample_boot_sector()


class _RealModeCPU:
    def __init__(self, boot_sector: bytes) -> None:
        if len(boot_sector) != BOOT_SECTOR_SIZE:
            raise EngineError("Önyükleme sektörü tam olarak 512 bayt olmalıdır.")
        if boot_sector[510:512] != b"\x55\xaa":
            raise EngineError("Geçerli önyükleme imzası 55 AA bulunamadı.")

        self.memory = bytearray(MEMORY_SIZE)
        self.memory[BOOT_ADDRESS : BOOT_ADDRESS + BOOT_SECTOR_SIZE] = boot_sector
        self.registers = [0] * 8
        self.segments = {"es": 0, "cs": 0, "ss": 0, "ds": 0}
        self.ip = BOOT_ADDRESS
        self.flags = 0
        self.output: list[str] = []
        self.instructions = 0

    def run(self) -> BootResult:
        while self.instructions < MAX_BOOT_STEPS:
            self.instructions += 1
            opcode = self._fetch8()
            if opcode == 0x90:
                continue
            if opcode == 0xF4:
                return BootResult("".join(self.output), self.instructions)
            if 0xB0 <= opcode <= 0xB7:
                self._set_reg8(opcode - 0xB0, self._fetch8())
                continue
            if 0xB8 <= opcode <= 0xBF:
                self.registers[opcode - 0xB8] = self._fetch16()
                continue
            if opcode == 0xAC:
                self._set_reg8(0, self._read8("ds", self.registers[6]))
                self.registers[6] = (self.registers[6] + 1) & 0xFFFF
                continue
            if opcode in (0x84, 0x85):
                self._test_reg(opcode)
                continue
            if 0x70 <= opcode <= 0x7F:
                self._conditional_jump(opcode)
                continue
            if opcode == 0xEB:
                self._relative_jump(8)
                continue
            if opcode == 0xE9:
                self._relative_jump(16)
                continue
            if opcode == 0xCD:
                self._interrupt(self._fetch8())
                continue
            if opcode == 0x3C:
                self._compare(self._get_reg8(0), self._fetch8(), 8)
                continue
            if opcode == 0x3D:
                self._compare(self.registers[0], self._fetch16(), 16)
                continue
            raise EngineError(f"Desteklenmeyen x86 işlemi: 0x{opcode:02x}.")
        raise EngineError(f"Önyükleme kodu {MAX_BOOT_STEPS} adım sınırını aştı.")

    def _fetch8(self) -> int:
        value = self._read8("cs", self.ip)
        self.ip = (self.ip + 1) & 0xFFFF
        return value

    def _fetch16(self) -> int:
        low = self._fetch8()
        return low | (self._fetch8() << 8)

    def _physical_address(self, segment: str, offset: int) -> int:
        return ((self.segments[segment] << 4) + offset) & 0xFFFFF

    def _read8(self, segment: str, offset: int) -> int:
        return self.memory[self._physical_address(segment, offset)]

    def _set_reg8(self, index: int, value: int) -> None:
        register = index & 3
        if index < 4:
            self.registers[register] = (
                (self.registers[register] & 0xFF00) | value
            )
        else:
            self.registers[register] = (
                (self.registers[register] & 0x00FF) | (value << 8)
            )

    def _get_reg8(self, index: int) -> int:
        register = self.registers[index & 3]
        return register & 0xFF if index < 4 else register >> 8

    def _test_reg(self, opcode: int) -> None:
        modrm = self._fetch8()
        if modrm >> 6 != 0b11:
            raise EngineError("Önyükleme motoru bellek operandını henüz desteklemiyor.")
        reg = (modrm >> 3) & 7
        rm = modrm & 7
        if opcode == 0x84:
            result = self._get_reg8(reg) & self._get_reg8(rm)
            width = 8
        else:
            result = self.registers[reg] & self.registers[rm]
            width = 16
        self._set_logic_flags(result, width)

    def _set_logic_flags(self, result: int, width: int) -> None:
        sign_bit = 1 << (width - 1)
        self.flags &= ~(CF | ZF | SF | OF)
        if result == 0:
            self.flags |= ZF
        if result & sign_bit:
            self.flags |= SF

    def _compare(self, left: int, right: int, width: int) -> None:
        mask = (1 << width) - 1
        result = (left - right) & mask
        sign_bit = 1 << (width - 1)
        self.flags &= ~(CF | ZF | SF | OF)
        if left < right:
            self.flags |= CF
        if result == 0:
            self.flags |= ZF
        if result & sign_bit:
            self.flags |= SF
        if ((left ^ right) & (left ^ result) & sign_bit) != 0:
            self.flags |= OF

    def _conditional_jump(self, opcode: int) -> None:
        conditions = {
            0x70: bool(self.flags & OF),
            0x71: not self.flags & OF,
            0x72: bool(self.flags & CF),
            0x73: not self.flags & CF,
            0x74: bool(self.flags & ZF),
            0x75: not self.flags & ZF,
            0x76: bool(self.flags & (CF | ZF)),
            0x77: not self.flags & (CF | ZF),
            0x78: bool(self.flags & SF),
            0x79: not self.flags & SF,
            0x7C: bool(self.flags & SF) != bool(self.flags & OF),
            0x7D: bool(self.flags & SF) == bool(self.flags & OF),
            0x7E: bool(self.flags & ZF)
            or bool(self.flags & SF) != bool(self.flags & OF),
            0x7F: not self.flags & ZF
            and bool(self.flags & SF) == bool(self.flags & OF),
        }
        displacement = self._signed(self._fetch8(), 8)
        if opcode not in conditions:
            raise EngineError(f"Desteklenmeyen koşullu atlama: 0x{opcode:02x}.")
        if conditions[opcode]:
            self.ip = (self.ip + displacement) & 0xFFFF

    def _relative_jump(self, width: int) -> None:
        raw = self._fetch8() if width == 8 else self._fetch16()
        self.ip = (self.ip + self._signed(raw, width)) & 0xFFFF

    def _interrupt(self, vector: int) -> None:
        if vector != 0x10:
            raise EngineError(
                f"BIOS kesmesi 0x{vector:02x} bu prototipte desteklenmiyor."
            )
        if self._get_reg8(4) != 0x0E:
            raise EngineError("BIOS 10h yalnızca metin karakteri işlevini destekliyor.")
        if len(self.output) >= MAX_BOOT_OUTPUT:
            raise EngineError("Önyükleme metin çıktısı sınırı aşıldı.")
        self.output.append(chr(self._get_reg8(0)))

    @staticmethod
    def _signed(value: int, width: int) -> int:
        sign_bit = 1 << (width - 1)
        return value - (1 << width) if value & sign_bit else value


def run_boot_sector(boot_sector: bytes) -> BootResult:
    return _RealModeCPU(boot_sector).run()
