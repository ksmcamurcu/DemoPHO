from fastapi import APIRouter, HTTPException

from app.engine.kvm import (
    KvmUnavailableError,
    kvm_is_available,
    run_kvm_smoke_test,
)
from app.engine.core import (
    MAX_PROGRAM_INSTRUCTIONS,
    MAX_STEPS,
    MEMORY_SIZE,
    REGISTER_COUNT,
    EngineError,
    run_program,
)
from app.engine.realmode import run_boot_sector
from app.schemas import (
    BootSectorRequest,
    BootSectorResponse,
    EngineResponse,
    KvmSmokeResponse,
    WoxProgram,
)

router = APIRouter(prefix="/engine", tags=["Wox motoru"])


@router.get("")
def engine_info() -> dict[str, object]:
    return {
        "name": "Wox Core",
        "version": "0.1.0-prototype",
        "instruction_set": "Wox Bytecode v1",
        "x86_boot_sector_execution": True,
        "x86_boot_sector_instruction_limit": 100_000,
        "register_count": REGISTER_COUNT,
        "memory_bytes": MEMORY_SIZE,
        "max_program_instructions": MAX_PROGRAM_INSTRUCTIONS,
        "max_execution_steps": MAX_STEPS,
        "host_access": False,
        "guest_os_boot": False,
        "kvm_acceleration_available": kvm_is_available(),
        "kvm_smoke_test": "/api/v1/engine/kvm-smoke",
        "planned_guest_systems": [
            "Ubuntu x86_64",
            "Parrot x86_64",
            "Pardus ARM64",
            "Windows 11 x86_64",
            "Windows 10 x86_64",
            "Windows Vista x86_64",
        ],
    }


@router.post("/run", response_model=EngineResponse)
def run_guest_program(payload: WoxProgram) -> EngineResponse:
    try:
        result = run_program(payload.program)
    except EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EngineResponse(
        registers=result.registers,
        output=result.output,
        steps=result.steps,
    )


@router.post("/boot-sector", response_model=BootSectorResponse)
def run_x86_boot_sector(payload: BootSectorRequest) -> BootSectorResponse:
    try:
        result = run_boot_sector(bytes.fromhex(payload.boot_sector_hex))
    except EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BootSectorResponse(
        output=result.output,
        instructions=result.instructions,
    )


@router.post("/kvm-smoke", response_model=KvmSmokeResponse)
def run_kvm_smoke() -> KvmSmokeResponse:
    try:
        result = run_kvm_smoke_test()
    except KvmUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EngineError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return KvmSmokeResponse(
        eax=result.eax,
        instructions=result.instructions,
        mode=result.mode,
        serial_output=result.serial_output,
        halted=result.halted,
    )
