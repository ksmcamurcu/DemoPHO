from dataclasses import dataclass

from app.schemas import WoxInstruction

REGISTER_COUNT = 4
MEMORY_SIZE = 64 * 1024
MAX_PROGRAM_INSTRUCTIONS = 512
MAX_STEPS = 10_000
WORD_SIZE = 8
WORD_MASK = (1 << 64) - 1


class EngineError(ValueError):
    pass


@dataclass(frozen=True)
class EngineResult:
    registers: list[int]
    output: list[str]
    steps: int


def _require_fields(instruction: WoxInstruction, *required: str) -> None:
    allowed = {"op", *required}
    supplied = instruction.model_fields_set
    has_missing_value = any(getattr(instruction, field) is None for field in required)
    if supplied != allowed or has_missing_value:
        raise EngineError(
            f"{instruction.op} işlemi yalnızca şu alanları kabul eder: "
            f"{', '.join(sorted(allowed - {'op'})) or 'ek alan yok'}."
        )


def run_program(program: list[WoxInstruction]) -> EngineResult:
    if not program:
        raise EngineError("Program en az bir işlem içermelidir.")
    if len(program) > MAX_PROGRAM_INSTRUCTIONS:
        raise EngineError(
            f"Program en fazla {MAX_PROGRAM_INSTRUCTIONS} işlem içerebilir."
        )

    registers = [0] * REGISTER_COUNT
    memory = bytearray(MEMORY_SIZE)
    output: list[str] = []
    pc = 0
    steps = 0

    while 0 <= pc < len(program):
        if steps >= MAX_STEPS:
            raise EngineError(f"Program {MAX_STEPS} işlem sınırını aştı.")
        instruction = program[pc]
        steps += 1
        op = instruction.op

        if op == "nop":
            _require_fields(instruction)
            pc += 1
        elif op == "load_imm":
            _require_fields(instruction, "register_index", "value")
            registers[instruction.register_index] = instruction.value
            pc += 1
        elif op in {"add", "sub"}:
            _require_fields(instruction, "register_index", "source")
            current = registers[instruction.register_index]
            operand = registers[instruction.source]
            registers[instruction.register_index] = (
                current + operand if op == "add" else current - operand
            ) & WORD_MASK
            pc += 1
        elif op == "load":
            _require_fields(instruction, "register_index", "address")
            end = instruction.address + WORD_SIZE
            registers[instruction.register_index] = int.from_bytes(
                memory[instruction.address : end], "little"
            )
            pc += 1
        elif op == "store":
            _require_fields(instruction, "source", "address")
            end = instruction.address + WORD_SIZE
            memory[instruction.address : end] = registers[
                instruction.source
            ].to_bytes(WORD_SIZE, "little")
            pc += 1
        elif op == "print":
            _require_fields(instruction, "register_index")
            output.append(str(registers[instruction.register_index]))
            pc += 1
        elif op == "jump":
            _require_fields(instruction, "target")
            pc = instruction.target
        elif op == "jump_if_zero":
            _require_fields(instruction, "register_index", "target")
            pc = (
                instruction.target
                if registers[instruction.register_index] == 0
                else pc + 1
            )
        elif op == "halt":
            _require_fields(instruction)
            return EngineResult(registers=registers, output=output, steps=steps)
        else:
            raise EngineError(f"Tanınmayan işlem: {op}")

    raise EngineError("Program durdurma işlemi olmadan bellek dışına çıktı.")
