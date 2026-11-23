from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class WoxInstruction(ApiModel):
    op: Literal[
        "nop",
        "load_imm",
        "add",
        "sub",
        "load",
        "store",
        "print",
        "jump",
        "jump_if_zero",
        "halt",
    ]
    register_index: int | None = Field(default=None, alias="register", ge=0, lt=4)
    source: int | None = Field(default=None, ge=0, lt=4)
    value: int | None = Field(default=None, ge=0, le=(1 << 64) - 1)
    address: int | None = Field(default=None, ge=0, le=(64 * 1024) - 8)
    target: int | None = Field(default=None, ge=0, lt=512)


class WoxProgram(ApiModel):
    program: list[WoxInstruction] = Field(min_length=1, max_length=512)


class BootSectorRequest(ApiModel):
    boot_sector_hex: str = Field(
        min_length=1024,
        max_length=1024,
        pattern=r"^[0-9a-fA-F]{1024}$",
        description="Tam olarak 512 baytlık x86 önyükleme sektörü; hex kodlanır.",
    )

    @model_validator(mode="after")
    def require_boot_signature(self) -> "BootSectorRequest":
        sector = bytes.fromhex(self.boot_sector_hex)
        if sector[510:512] != b"\x55\xaa":
            raise ValueError("Geçerli önyükleme imzası 55 AA bulunamadı.")
        return self


class EngineResponse(ApiModel):
    engine: str = "Wox Core"
    registers: list[int]
    output: list[str]
    steps: int
    halted: bool = True


class BootSectorResponse(ApiModel):
    engine: str = "Wox x86 Real Mode"
    output: str
    instructions: int
    halted: bool = True


class KvmSmokeResponse(ApiModel):
    engine: str = "Wox KVM vCPU"
    eax: int
    instructions: int
    mode: str
    serial_output: str
    halted: bool
