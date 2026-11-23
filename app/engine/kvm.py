import ctypes
import mmap
import multiprocessing
import os
import signal
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.engine.core import EngineError
from app.engine.devices import KvmIoBus, ReadOnlyIsoDevice

KVM_DEVICE = "/dev/kvm"
KVM_API_VERSION = 12
GUEST_MEMORY_SIZE = 1 << 20
GUEST_CODE_ADDRESS = 0x10000
GUEST_GDT_ADDRESS = 0x2000
GUEST_PML4_ADDRESS = 0x3000
GUEST_PDPT_ADDRESS = 0x4000
GUEST_PD_ADDRESS = 0x5000
MAX_SINGLE_STEP_INSTRUCTIONS = 16
MAX_CPUID_ENTRIES = 256
MIN_PC_MEMORY_SIZE = 16 << 20
MAX_PC_MEMORY_SIZE = 1 << 30
MAX_FIRMWARE_TIMEOUT_SECONDS = 600
BIOS_LOW_MEMORY_START = 0xC0000
BIOS_MEMORY_SIZE = 0x40000
BIOS_OPTION_ROM_END = 0xE0000
BIOS_ROM_START = 0xE0000
BIOS_ROM_SIZE = 0x20000
BIOS_RESET_ALIAS = 0xFFFF0000
BIOS_RESET_ALIAS_SIZE = 0x10000
BIOS_FLASH_ALIAS = 0xFFF00000
BIOS_FLASH_ALIAS_SIZE = 0x100000
VGA_ROM_MAX_SIZE = 0x8000
KVM_MEM_READONLY = 1 << 1

KVM_GET_API_VERSION = 0xAE00
KVM_CREATE_VM = 0xAE01
KVM_CREATE_IRQCHIP = 0xAE60
KVM_CREATE_PIT2 = 0x4040AE77
KVM_SET_TSS_ADDR = 0xAE47
KVM_GET_VCPU_MMAP_SIZE = 0xAE04
KVM_GET_SUPPORTED_CPUID = 0xC008AE05
KVM_CREATE_VCPU = 0xAE41
KVM_SET_CPUID2 = 0x4008AE90
KVM_RUN = 0xAE80
KVM_EXIT_IO = 2
KVM_EXIT_DEBUG = 4
KVM_EXIT_HLT = 5
KVM_EXIT_MMIO = 6
KVM_EXIT_SHUTDOWN = 8
KVM_EXIT_FAIL_ENTRY = 9
KVM_EXIT_INTERNAL_ERROR = 17
KVM_EXIT_IO_OUT = 1


def _iow(number: int, size: int) -> int:
    return (1 << 30) | (size << 16) | (0xAE << 8) | number


def _ior(number: int, size: int) -> int:
    return (2 << 30) | (size << 16) | (0xAE << 8) | number


class _MemoryRegion(ctypes.Structure):
    _fields_ = [
        ("slot", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("guest_phys_addr", ctypes.c_uint64),
        ("memory_size", ctypes.c_uint64),
        ("userspace_addr", ctypes.c_uint64),
    ]


class _Segment(ctypes.Structure):
    _fields_ = [
        ("base", ctypes.c_uint64),
        ("limit", ctypes.c_uint32),
        ("selector", ctypes.c_uint16),
        ("type", ctypes.c_uint8),
        ("present", ctypes.c_uint8),
        ("dpl", ctypes.c_uint8),
        ("db", ctypes.c_uint8),
        ("s", ctypes.c_uint8),
        ("l", ctypes.c_uint8),
        ("g", ctypes.c_uint8),
        ("avl", ctypes.c_uint8),
        ("unusable", ctypes.c_uint8),
        ("padding", ctypes.c_uint8),
    ]


class _DTable(ctypes.Structure):
    _fields_ = [
        ("base", ctypes.c_uint64),
        ("limit", ctypes.c_uint16),
        ("padding", ctypes.c_uint16 * 3),
    ]


class _SpecialRegisters(ctypes.Structure):
    _fields_ = [
        ("cs", _Segment),
        ("ds", _Segment),
        ("es", _Segment),
        ("fs", _Segment),
        ("gs", _Segment),
        ("ss", _Segment),
        ("tr", _Segment),
        ("ldt", _Segment),
        ("gdt", _DTable),
        ("idt", _DTable),
        ("cr0", ctypes.c_uint64),
        ("cr2", ctypes.c_uint64),
        ("cr3", ctypes.c_uint64),
        ("cr4", ctypes.c_uint64),
        ("cr8", ctypes.c_uint64),
        ("efer", ctypes.c_uint64),
        ("apic_base", ctypes.c_uint64),
        ("interrupt_bitmap", ctypes.c_uint64 * 4),
    ]


class _Registers(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "rax",
            "rbx",
            "rcx",
            "rdx",
            "rsi",
            "rdi",
            "rsp",
            "rbp",
            "r8",
            "r9",
            "r10",
            "r11",
            "r12",
            "r13",
            "r14",
            "r15",
            "rip",
            "rflags",
        )
    ]


class _GuestDebug(ctypes.Structure):
    _fields_ = [
        ("control", ctypes.c_uint32),
        ("padding", ctypes.c_uint32),
        ("debugreg", ctypes.c_uint64 * 8),
    ]


class _CpuidEntry(ctypes.Structure):
    _fields_ = [
        ("function", ctypes.c_uint32),
        ("index", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("eax", ctypes.c_uint32),
        ("ebx", ctypes.c_uint32),
        ("ecx", ctypes.c_uint32),
        ("edx", ctypes.c_uint32),
        ("padding", ctypes.c_uint32 * 3),
    ]


class _CpuidBuffer(ctypes.Structure):
    _fields_ = [
        ("nent", ctypes.c_uint32),
        ("padding", ctypes.c_uint32),
        ("entries", _CpuidEntry * MAX_CPUID_ENTRIES),
    ]


class _PitConfig(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint32), ("padding", ctypes.c_uint32 * 15)]


KVM_SET_USER_MEMORY_REGION = _iow(0x46, ctypes.sizeof(_MemoryRegion))
KVM_GET_SREGS = _ior(0x83, ctypes.sizeof(_SpecialRegisters))
KVM_SET_SREGS = _iow(0x84, ctypes.sizeof(_SpecialRegisters))
KVM_GET_REGS = _ior(0x81, ctypes.sizeof(_Registers))
KVM_SET_REGS = _iow(0x82, ctypes.sizeof(_Registers))
KVM_SET_GUEST_DEBUG = _iow(0x9B, ctypes.sizeof(_GuestDebug))


@dataclass(frozen=True, slots=True)
class KvmSmokeResult:
    eax: int
    instructions: int
    mode: str
    serial_output: str
    halted: bool


@dataclass(frozen=True, slots=True)
class KvmBiosResult:
    exits: int
    screen_text: str
    halted: bool
    terminal_reason: str
    rip: int
    cs_base: int
    cs_selector: int
    serial_output: str
    debug_output: str
    atapi_commands: tuple[int, ...]
    atapi_reads: tuple[tuple[int, int], ...]
    io_trace: tuple[tuple[str, int, int, bytes], ...]
    instruction_bytes: bytes


class KvmUnavailableError(EngineError):
    pass


class _ProbeInterrupted(Exception):
    pass


def _interrupt_probe(signum, frame) -> None:
    raise _ProbeInterrupted


def kvm_is_available() -> bool:
    if sys.platform != "linux" or not os.access(KVM_DEVICE, os.R_OK | os.W_OK):
        return False

    import fcntl

    try:
        descriptor = os.open(KVM_DEVICE, os.O_RDWR | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        return fcntl.ioctl(descriptor, KVM_GET_API_VERSION) == KVM_API_VERSION
    except OSError:
        return False
    finally:
        os.close(descriptor)


def _ioctl_struct(descriptor: int, request: int, value: ctypes.Structure) -> None:
    import fcntl

    payload = bytearray(
        ctypes.string_at(ctypes.addressof(value), ctypes.sizeof(value))
    )
    fcntl.ioctl(descriptor, request, payload, True)
    ctypes.memmove(ctypes.addressof(value), bytes(payload), len(payload))


def _set_supported_cpuid(kvm_fd: int, vcpu_fd: int) -> None:
    import fcntl

    cpuid = _CpuidBuffer()
    cpuid.nent = MAX_CPUID_ENTRIES
    payload = bytearray(
        ctypes.string_at(ctypes.addressof(cpuid), ctypes.sizeof(cpuid))
    )
    fcntl.ioctl(kvm_fd, KVM_GET_SUPPORTED_CPUID, payload, True)
    ctypes.memmove(ctypes.addressof(cpuid), bytes(payload), len(payload))
    _ioctl_struct(vcpu_fd, KVM_SET_CPUID2, cpuid)


def _register_memory_region(
    vm_fd: int,
    slot: int,
    guest_address: int,
    memory: mmap.mmap,
    *,
    memory_offset: int = 0,
    size: int | None = None,
    flags: int = 0,
) -> None:
    length = size if size is not None else len(memory) - memory_offset
    region = _MemoryRegion(
        slot=slot,
        flags=flags,
        guest_phys_addr=guest_address,
        memory_size=length,
        userspace_addr=ctypes.addressof(ctypes.c_char.from_buffer(memory, memory_offset)),
    )
    _ioctl_struct(vm_fd, KVM_SET_USER_MEMORY_REGION, region)


def _handle_io_exit(run_mapping: mmap.mmap, io_bus: KvmIoBus) -> None:
    direction, size, port, count = struct.unpack_from("=BBHI", run_mapping, 32)
    data_offset = struct.unpack_from("=Q", run_mapping, 40)[0]
    for index in range(count):
        offset = data_offset + index * size
        if direction == KVM_EXIT_IO_OUT:
            io_bus.write(port, bytes(run_mapping[offset : offset + size]))
        elif direction == 0:
            run_mapping[offset : offset + size] = io_bus.read(port, size)
        else:
            raise EngineError("Wox konuk I/O yönü geçersiz.")


def _handle_mmio_exit(
    run_mapping: mmap.mmap,
    guest_memory: mmap.mmap,
    bios_memory: mmap.mmap,
    flash_memory: mmap.mmap,
) -> None:
    address = struct.unpack_from("=Q", run_mapping, 32)[0]
    length = struct.unpack_from("=I", run_mapping, 48)[0]
    is_write = run_mapping[52]
    if length < 1 or length > 8:
        raise EngineError("Konuk MMIO isteğinin boyutu geçersiz.")
    if is_write:
        if (
            BIOS_ROM_START <= address
            and address + length <= (1 << 20)
        ) or (
            BIOS_RESET_ALIAS <= address
            and address + length <= (1 << 32)
        ) or (
            BIOS_FLASH_ALIAS <= address
            and address + length <= BIOS_FLASH_ALIAS + BIOS_FLASH_ALIAS_SIZE
        ):
            return
        raise EngineError("Wox KVM konuğu desteklenmeyen MMIO yazımı yaptı.")

    if BIOS_LOW_MEMORY_START <= address and address + length <= BIOS_OPTION_ROM_END:
        memory = bios_memory
        offset = address - BIOS_LOW_MEMORY_START
    elif BIOS_ROM_START <= address and address + length <= (1 << 20):
        memory = bios_memory
        offset = BIOS_MEMORY_SIZE - BIOS_ROM_SIZE + address - BIOS_ROM_START
    elif BIOS_RESET_ALIAS <= address and address + length <= (1 << 32):
        memory = bios_memory
        offset = (
            BIOS_MEMORY_SIZE - BIOS_RESET_ALIAS_SIZE
            + address - BIOS_RESET_ALIAS
        )
    elif BIOS_FLASH_ALIAS <= address and address + length <= BIOS_FLASH_ALIAS + BIOS_FLASH_ALIAS_SIZE:
        memory = flash_memory
        offset = address - BIOS_FLASH_ALIAS
        if offset + length > BIOS_FLASH_ALIAS_SIZE:
            raise EngineError("Wox KVM konusu BIOS flash eşliği sınırını aştı.")
    elif address + length <= len(guest_memory):
        memory = guest_memory
        offset = address
    else:
        raise EngineError("Wox KVM konuğu desteklenmeyen MMIO okuması yaptı.")
    run_mapping[40 : 40 + length] = memory[offset : offset + length]


def _bios_result(
    vcpu_fd: int,
    guest_memory: mmap.mmap,
    bios_memory: mmap.mmap,
    high_bios_memory: mmap.mmap,
    exits: int,
    terminal_reason: str,
    io_bus: KvmIoBus,
) -> KvmBiosResult:
    registers = _Registers()
    segments = _SpecialRegisters()
    _ioctl_struct(vcpu_fd, KVM_GET_REGS, registers)
    _ioctl_struct(vcpu_fd, KVM_GET_SREGS, segments)
    instruction_address = segments.cs.base + registers.rip
    if BIOS_LOW_MEMORY_START <= instruction_address < BIOS_OPTION_ROM_END:
        instruction_memory = bios_memory
        instruction_offset = instruction_address - BIOS_LOW_MEMORY_START
    elif BIOS_ROM_START <= instruction_address < (1 << 20):
        instruction_memory = bios_memory
        instruction_offset = (
            BIOS_MEMORY_SIZE - BIOS_ROM_SIZE
            + instruction_address - BIOS_ROM_START
        )
    elif BIOS_RESET_ALIAS <= instruction_address < (1 << 32):
        instruction_memory = bios_memory
        instruction_offset = (
            BIOS_MEMORY_SIZE - BIOS_RESET_ALIAS_SIZE
            + instruction_address - BIOS_RESET_ALIAS
        )
    elif BIOS_FLASH_ALIAS <= instruction_address < BIOS_FLASH_ALIAS + BIOS_FLASH_ALIAS_SIZE:
        instruction_memory = high_bios_memory
        instruction_offset = instruction_address - BIOS_FLASH_ALIAS
    else:
        instruction_memory = guest_memory
        instruction_offset = instruction_address
    instruction_bytes = (
        bytes(instruction_memory[instruction_offset : instruction_offset + 32])
        if instruction_offset + 32 <= len(instruction_memory)
        else b""
    )
    text = guest_memory[0xB8000 : 0xB8000 + 80 * 25 * 2]
    screen = "".join(
        chr(text[offset])
        for offset in range(0, len(text), 2)
        if 32 <= text[offset] < 127
    )
    return KvmBiosResult(
        exits,
        screen.strip(),
        terminal_reason == "hlt",
        terminal_reason,
        registers.rip,
        segments.cs.base,
        segments.cs.selector,
        "".join(io_bus.serial_output),
        "".join(io_bus.debug_output),
        tuple(io_bus.cdrom.command_history) if io_bus.cdrom is not None else (),
        tuple(io_bus.cdrom.read_requests) if io_bus.cdrom is not None else (),
        tuple(io_bus.io_trace),
        instruction_bytes,
    )


def _configure_long_mode(
    descriptor: int,
    segments: _SpecialRegisters,
    guest_memory: mmap.mmap,
) -> None:
    struct.pack_into(
        "<QQQ",
        guest_memory,
        GUEST_GDT_ADDRESS,
        0,
        0x00CF9A000000FFFF,
        0x00CF92000000FFFF,
    )
    struct.pack_into("<Q", guest_memory, GUEST_PML4_ADDRESS, GUEST_PDPT_ADDRESS | 3)
    struct.pack_into("<Q", guest_memory, GUEST_PDPT_ADDRESS, GUEST_PD_ADDRESS | 3)
    struct.pack_into("<Q", guest_memory, GUEST_PD_ADDRESS, 0x83)

    segments.gdt.base = GUEST_GDT_ADDRESS
    segments.gdt.limit = 23
    segments.cr0 = (segments.cr0 & ~((1 << 30) | (1 << 29) | (1 << 31))) | 1 | (1 << 4)
    segments.cr3 = GUEST_PML4_ADDRESS
    segments.cr4 = 1 << 5
    segments.efer = 1 << 8

    code = segments.cs
    code.base = 0
    code.limit = 0xFFFFFFFF
    code.selector = 0x08
    code.type = 0xB
    code.present = 1
    code.dpl = 0
    code.db = 1
    code.s = 1
    code.l = 0
    code.g = 1
    code.avl = code.unusable = code.padding = 0

    for name in ("ds", "es", "fs", "gs", "ss"):
        segment = getattr(segments, name)
        segment.base = 0
        segment.limit = 0xFFFFFFFF
        segment.selector = 0x10
        segment.type = 0x3
        segment.present = 1
        segment.dpl = 0
        segment.db = 1
        segment.s = 1
        segment.l = 0
        segment.g = 1
        segment.avl = segment.unusable = segment.padding = 0

    _ioctl_struct(descriptor, KVM_SET_SREGS, segments)
    segments.cr0 |= 1 << 31
    segments.efer |= 1 << 10
    _ioctl_struct(descriptor, KVM_SET_SREGS, segments)

    struct.pack_into(
        "<Q",
        guest_memory,
        GUEST_GDT_ADDRESS + 8,
        0x00AF9A000000FFFF,
    )
    segments.cs.db = 0
    segments.cs.l = 1
    _ioctl_struct(descriptor, KVM_SET_SREGS, segments)


def run_kvm_smoke_test() -> KvmSmokeResult:
    if sys.platform != "linux":
        raise KvmUnavailableError("Wox KVM motoru şu an yalnızca Linux'ta destekleniyor.")

    import fcntl

    if not kvm_is_available():
        raise KvmUnavailableError(
            "KVM kullanılamıyor. /dev/kvm erişimini ve işlemci sanallaştırmasını denetleyin."
        )

    kvm_fd = vm_fd = vcpu_fd = -1
    guest_memory = run_mapping = None
    try:
        kvm_fd = os.open(KVM_DEVICE, os.O_RDWR | os.O_CLOEXEC)
        vm_fd = fcntl.ioctl(kvm_fd, KVM_CREATE_VM, 0)
        guest_memory = mmap.mmap(
            -1,
            GUEST_MEMORY_SIZE,
            flags=mmap.MAP_SHARED | mmap.MAP_ANONYMOUS,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )
        guest_code = (
            b"\xba\x70\x00\x00\x00\xb0\xb5\xee\x83\xc2\x01\xec\x3c\x03\x75\x0d"
            b"\xba\xf8\x03\x00\x00\xb0\x57\xee\xb8\x2a\x00\x00\x00\xf4"
        )
        guest_memory[
            GUEST_CODE_ADDRESS : GUEST_CODE_ADDRESS + len(guest_code)
        ] = guest_code

        _register_memory_region(vm_fd, 0, 0, guest_memory)

        vcpu_fd = fcntl.ioctl(vm_fd, KVM_CREATE_VCPU, 0)
        _set_supported_cpuid(kvm_fd, vcpu_fd)
        mmap_size = fcntl.ioctl(kvm_fd, KVM_GET_VCPU_MMAP_SIZE)
        run_mapping = mmap.mmap(
            vcpu_fd,
            mmap_size,
            flags=mmap.MAP_SHARED,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )

        segments = _SpecialRegisters()
        _ioctl_struct(vcpu_fd, KVM_GET_SREGS, segments)
        _configure_long_mode(vcpu_fd, segments, guest_memory)

        registers = _Registers()
        registers.rip = GUEST_CODE_ADDRESS
        registers.rsp = GUEST_MEMORY_SIZE - 0x100
        registers.rflags = 2
        _ioctl_struct(vcpu_fd, KVM_SET_REGS, registers)

        debug = _GuestDebug()
        debug.control = 0x1 | 0x2
        _ioctl_struct(vcpu_fd, KVM_SET_GUEST_DEBUG, debug)

        instructions = 0
        io_bus = KvmIoBus()
        while instructions < MAX_SINGLE_STEP_INSTRUCTIONS:
            fcntl.ioctl(vcpu_fd, KVM_RUN, 0)
            instructions += 1
            exit_reason = struct.unpack_from("=I", run_mapping, 8)[0]
            if exit_reason == KVM_EXIT_DEBUG:
                continue
            if exit_reason == KVM_EXIT_IO:
                _handle_io_exit(run_mapping, io_bus)
                continue
            if exit_reason == KVM_EXIT_HLT:
                _ioctl_struct(vcpu_fd, KVM_GET_REGS, registers)
                return KvmSmokeResult(
                    eax=registers.rax & 0xFFFFFFFF,
                    instructions=instructions,
                    mode="x86_64 long mode",
                    serial_output="".join(io_bus.serial_output),
                    halted=True,
                )
            raise EngineError(
                f"Wox KVM örnek konuğu beklenmeyen çıkış verdi: {exit_reason}."
            )
        raise EngineError("Wox KVM örnek konuğu komut sınırını aştı.")
    except OSError as exc:
        raise EngineError(f"Wox KVM motoru çalıştırılamadı: {exc}") from exc
    finally:
        if run_mapping is not None:
            run_mapping.close()
        if guest_memory is not None:
            guest_memory.close()
        for descriptor in (vcpu_fd, vm_fd, kvm_fd):
            if descriptor >= 0:
                os.close(descriptor)


def _run_bios_probe(
    firmware_path: str | Path,
    *,
    vga_bios_path: str | Path | None = None,
    iso_path: str | Path | None = None,
    memory_size: int = 64 << 20,
    max_exits: int = 100_000,
) -> KvmBiosResult:
    if sys.platform != "linux":
        raise KvmUnavailableError("Wox KVM motoru şu an yalnızca Linux'ta destekleniyor.")
    if memory_size < MIN_PC_MEMORY_SIZE or memory_size > MAX_PC_MEMORY_SIZE:
        raise EngineError("Konuk belleği 16 MiB ile 1 GiB arasında olmalıdır.")
    if memory_size % (2 << 20):
        raise EngineError("Konuk belleği 2 MiB katı olmalıdır.")
    if max_exits < 1 or max_exits > 1_000_000:
        raise EngineError("Firmware çıkış sınırı geçersiz.")

    firmware = Path(firmware_path).expanduser().resolve(strict=True)
    if not firmware.is_file():
        raise EngineError("Firmware yolu normal bir dosya olmalıdır.")
    if firmware.stat().st_size != BIOS_MEMORY_SIZE:
        raise EngineError("SeaBIOS firmware dosyası tam 256 KiB olmalıdır.")
    image = firmware.read_bytes()
    if len(image) != BIOS_MEMORY_SIZE:
        raise EngineError("SeaBIOS firmware dosyası tam 256 KiB olmalıdır.")
    vga_image = b""
    if vga_bios_path is not None:
        vga_firmware = Path(vga_bios_path).expanduser().resolve(strict=True)
        if not vga_firmware.is_file():
            raise EngineError("VGA firmware yolu normal bir dosya olmalıdır.")
        if not 512 <= vga_firmware.stat().st_size <= VGA_ROM_MAX_SIZE:
            raise EngineError("VGA firmware imajı geçerli bir option ROM değil.")
        vga_image = vga_firmware.read_bytes()
        if (
            not 512 <= len(vga_image) <= VGA_ROM_MAX_SIZE
            or len(vga_image) % 512
            or vga_image[:2] != b"\x55\xaa"
        ):
            raise EngineError("VGA firmware imajı geçerli bir option ROM değil.")

    if not kvm_is_available():
        raise KvmUnavailableError(
            "KVM kullanılamıyor. /dev/kvm erişimini ve işlemci sanallaştırmasını denetleyin."
        )

    import fcntl

    kvm_fd = vm_fd = vcpu_fd = -1
    guest_memory = bios_memory = high_bios_memory = run_mapping = None
    iso_device = None
    try:
        if iso_path is not None:
            iso_device = ReadOnlyIsoDevice(iso_path)
        kvm_fd = os.open(KVM_DEVICE, os.O_RDWR | os.O_CLOEXEC)
        vm_fd = fcntl.ioctl(kvm_fd, KVM_CREATE_VM, 0)
        fcntl.ioctl(vm_fd, KVM_CREATE_IRQCHIP, 0)
        _ioctl_struct(vm_fd, KVM_CREATE_PIT2, _PitConfig())
        fcntl.ioctl(vm_fd, KVM_SET_TSS_ADDR, 0x7FFBD000)

        guest_memory = mmap.mmap(
            -1,
            memory_size,
            flags=mmap.MAP_SHARED | mmap.MAP_ANONYMOUS,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )
        bios_memory = mmap.mmap(
            -1,
            BIOS_MEMORY_SIZE,
            flags=mmap.MAP_SHARED | mmap.MAP_ANONYMOUS,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )
        bios_memory[:] = image
        high_bios_memory = mmap.mmap(
            -1,
            BIOS_FLASH_ALIAS_SIZE,
            flags=mmap.MAP_SHARED | mmap.MAP_ANONYMOUS,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )
        high_bios_memory[:] = b"\0" * BIOS_FLASH_ALIAS_SIZE
        high_bios_memory[0xC0000:0xE0000] = image[0:0x20000]
        high_bios_memory[0xE0000:0x100000] = image[0x20000:0x40000]
        if vga_image:
            bios_memory[: len(vga_image)] = vga_image
        _register_memory_region(
            vm_fd, 0, 0, guest_memory, size=BIOS_LOW_MEMORY_START
        )
        _register_memory_region(
            vm_fd,
            1,
            BIOS_LOW_MEMORY_START,
            bios_memory,
            size=BIOS_OPTION_ROM_END - BIOS_LOW_MEMORY_START,
        )
        # SeaBIOS shadows this low mapping; only the high flash alias is read-only.
        _register_memory_region(
            vm_fd,
            2,
            BIOS_ROM_START,
            bios_memory,
            memory_offset=BIOS_MEMORY_SIZE - BIOS_ROM_SIZE,
            size=BIOS_ROM_SIZE,
        )
        _register_memory_region(
            vm_fd,
            3,
            1 << 20,
            guest_memory,
            memory_offset=1 << 20,
            size=max(0, memory_size - (1 << 20)),
        )
        _register_memory_region(
            vm_fd,
            4,
            BIOS_FLASH_ALIAS,
            high_bios_memory,
            size=BIOS_FLASH_ALIAS_SIZE,
            flags=KVM_MEM_READONLY,
        )

        vcpu_fd = fcntl.ioctl(vm_fd, KVM_CREATE_VCPU, 0)
        _set_supported_cpuid(kvm_fd, vcpu_fd)
        mmap_size = fcntl.ioctl(kvm_fd, KVM_GET_VCPU_MMAP_SIZE)
        run_mapping = mmap.mmap(
            vcpu_fd,
            mmap_size,
            flags=mmap.MAP_SHARED,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )
        io_bus = KvmIoBus(
            iso_device,
            ignore_unknown=True,
            memory_size=memory_size,
        )
        registers = _Registers()
        registers.rip = 0xFFF0
        registers.rsp = 0
        registers.rbp = 0
        registers.rflags = 2
        _ioctl_struct(vcpu_fd, KVM_SET_REGS, registers)
        exits = 0
        while exits < max_exits:
            try:
                fcntl.ioctl(vcpu_fd, KVM_RUN, 0)
            except (_ProbeInterrupted, InterruptedError):
                return _bios_result(
                    vcpu_fd,
                    guest_memory,
                    bios_memory,
                    high_bios_memory,
                    exits,
                    "interrupted",
                    io_bus,
                )
            exits += 1
            exit_reason = struct.unpack_from("=I", run_mapping, 8)[0]
            if exit_reason == KVM_EXIT_IO:
                _handle_io_exit(run_mapping, io_bus)
            elif exit_reason == KVM_EXIT_MMIO:
                _handle_mmio_exit(
                    run_mapping,
                    guest_memory,
                    bios_memory,
                    high_bios_memory,
                )
            elif exit_reason == KVM_EXIT_HLT:
                return _bios_result(
                    vcpu_fd,
                    guest_memory,
                    bios_memory,
                    high_bios_memory,
                    exits,
                    "hlt",
                    io_bus,
                )
            elif exit_reason == KVM_EXIT_SHUTDOWN:
                return _bios_result(
                    vcpu_fd,
                    guest_memory,
                    bios_memory,
                    high_bios_memory,
                    exits,
                    "shutdown",
                    io_bus,
                )
            elif exit_reason in {KVM_EXIT_FAIL_ENTRY, KVM_EXIT_INTERNAL_ERROR}:
                suberror = struct.unpack_from("=I", run_mapping, 16)[0]
                return _bios_result(
                    vcpu_fd,
                    guest_memory,
                    bios_memory,
                    high_bios_memory,
                    exits,
                    f"kvm_error_{exit_reason}_suberror_{suberror}",
                    io_bus,
                )
            else:
                raise EngineError(
                    f"SeaBIOS beklenmeyen KVM çıkışı verdi: {exit_reason}."
                )
        return _bios_result(
            vcpu_fd,
            guest_memory,
            bios_memory,
            high_bios_memory,
            exits,
            "exit_limit",
            io_bus,
        )
    except OSError as exc:
        raise EngineError(f"SeaBIOS KVM üzerinde başlatılamadı: {exc}") from exc
    finally:
        if run_mapping is not None:
            run_mapping.close()
        if bios_memory is not None:
            bios_memory.close()
        if guest_memory is not None:
            guest_memory.close()
        if iso_device is not None:
            iso_device.close()
        for descriptor in (vcpu_fd, vm_fd, kvm_fd):
            if descriptor >= 0:
                os.close(descriptor)


def _bios_probe_worker(
    connection,
    firmware_path,
    vga_bios_path,
    iso_path,
    memory_size,
    max_exits,
) -> None:
    signal.signal(signal.SIGUSR1, _interrupt_probe)
    try:
        result = _run_bios_probe(
            firmware_path,
            vga_bios_path=vga_bios_path,
            iso_path=iso_path,
            memory_size=memory_size,
            max_exits=max_exits,
        )
        connection.send((True, result))
    except Exception as exc:
        connection.send((False, type(exc).__name__, str(exc)))
    finally:
        connection.close()


def run_bios_probe(
    firmware_path: str | Path,
    *,
    vga_bios_path: str | Path | None = None,
    iso_path: str | Path | None = None,
    memory_size: int = 64 << 20,
    max_exits: int = 100_000,
    timeout_seconds: int = 30,
) -> KvmBiosResult:
    if sys.platform != "linux":
        raise KvmUnavailableError("Wox KVM motoru şu an yalnızca Linux'ta destekleniyor.")
    if not 1 <= timeout_seconds <= MAX_FIRMWARE_TIMEOUT_SECONDS:
        raise EngineError(
            f"Firmware zaman aşımı 1 ile {MAX_FIRMWARE_TIMEOUT_SECONDS} saniye arasında olmalıdır."
        )

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_bios_probe_worker,
        args=(
            sender,
            str(firmware_path),
            str(vga_bios_path) if vga_bios_path is not None else None,
            str(iso_path) if iso_path is not None else None,
            memory_size,
            max_exits,
        ),
    )
    try:
        process.start()
        sender.close()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if receiver.poll(min(0.1, deadline - time.monotonic())):
                try:
                    response = receiver.recv()
                except EOFError:
                    break
                process.join(timeout=1)
                if response[0]:
                    return response[1]
                message = response[2]
                if response[1] == "KvmUnavailableError":
                    raise KvmUnavailableError(message)
                raise EngineError(message)
            if not process.is_alive():
                break
        if process.is_alive():
            os.kill(process.pid, signal.SIGUSR1)
            if receiver.poll(2):
                try:
                    response = receiver.recv()
                except EOFError:
                    response = None
                process.join(timeout=1)
                if response is not None and response[0]:
                    return response[1]
                if response is not None:
                    message = response[2]
                    if response[1] == "KvmUnavailableError":
                        raise KvmUnavailableError(message)
                    raise EngineError(message)
            if process.is_alive():
                process.terminate()
                process.join()
            raise EngineError(
                f"Firmware denemesi {timeout_seconds} saniyelik zaman sınırını aştı."
            )
        raise EngineError("Firmware denemesi sonuç üretmeden sona erdi.")
    finally:
        receiver.close()
        sender.close()
        if process.is_alive():
            process.terminate()
            process.join()
