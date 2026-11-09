
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


IndexCategory = Literal[
    "market_index",
    "volatility_index",
]


class IndexCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=100)
    exchange: str = Field(min_length=2, max_length=10)

    category: IndexCategory = "market_index"

    description: str | None = None

    display_order: int = Field(default=0, ge=0)
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, value: str) -> str:
        return value.strip().upper()


class IndexUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    exchange: str | None = Field(default=None, min_length=2, max_length=10)
    category: IndexCategory | None = None
    description: str | None = None
    display_order: int | None = Field(default=None, ge=0)


class IndexStatusUpdate(BaseModel):
    is_active: bool


class IndexRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    exchange: str
    category: str
    description: str | None
    is_active: bool
    display_order: int
