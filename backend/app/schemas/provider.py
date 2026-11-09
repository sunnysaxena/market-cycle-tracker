from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderMappingCreate(BaseModel):
    provider_name: str = Field(min_length=2, max_length=50)
    provider_symbol: str = Field(min_length=1, max_length=100)

    exchange_segment: str | None = None
    instrument_token: str | None = None
    notes: str | None = None

    is_active: bool = True

    @field_validator("provider_name")
    @classmethod
    def normalize_provider_name(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("provider_symbol")
    @classmethod
    def normalize_provider_symbol(cls, value: str) -> str:
        return value.strip()


class ProviderMappingUpdate(BaseModel):
    provider_name: str | None = Field(default=None, min_length=2, max_length=50)
    provider_symbol: str | None = Field(default=None, min_length=1, max_length=100)

    exchange_segment: str | None = None
    instrument_token: str | None = None
    notes: str | None = None

    @field_validator("provider_name")
    @classmethod
    def normalize_provider_name(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @field_validator("provider_symbol")
    @classmethod
    def normalize_provider_symbol(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ProviderMappingStatusUpdate(BaseModel):
    is_active: bool


class ProviderMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    index_id: int
    provider_name: str
    provider_symbol: str

    exchange_segment: str | None
    instrument_token: str | None
    is_active: bool
    notes: str | None
