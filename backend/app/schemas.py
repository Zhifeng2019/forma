from typing import Literal
from pydantic import BaseModel, Field, EmailStr, model_validator, field_validator
from .authentication.identities import canonical_phone


class ContactInput(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)

    @model_validator(mode='after')
    def one_contact(self):
        if (self.email is None) == (self.phone is None):
            raise ValueError('Provide either an email address or a mainland China mobile number')
        if self.phone is not None:
            self.phone = canonical_phone(self.phone)
        return self


class RegisterInput(ContactInput):
    name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=128)

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('Enter a name with at least 2 characters')
        return value.strip()


class LoginInput(BaseModel):
    identifier: str | None = Field(default=None, min_length=3, max_length=320)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    password: str = Field(max_length=128)

    @model_validator(mode='after')
    def login_identity(self):
        if (self.identifier is None) == (self.email is None):
            raise ValueError('Provide one email address or mobile number to sign in')
        return self


class ResendRegistrationInput(BaseModel):
    challenge_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class VerifyRegistrationInput(ResendRegistrationInput):
    code: str = Field(pattern=r'^[0-9]{6}$')


class ResetPasswordInput(VerifyRegistrationInput):
    password: str = Field(min_length=8, max_length=128)


class UserUpdateInput(BaseModel):
    status: Literal['active', 'disabled', 'rejected'] | None = None
    role: Literal['admin', 'user'] | None = None


class ProviderInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    base_url: str = 'https://api.openai.com/v1'
    model: str = Field(min_length=1, max_length=120)
    api_key: str = ''
    enabled: bool = True
    input_price_per_million: float | None = Field(default=None, ge=0, le=1_000_000_000, allow_inf_nan=False)
    output_price_per_million: float | None = Field(default=None, ge=0, le=1_000_000_000, allow_inf_nan=False)
    currency: str = Field(default='USD', min_length=3, max_length=3, pattern='^[A-Za-z]{3}$')


class PreferenceInput(BaseModel):
    provider_id: int | None = None
    auto_mode: bool = False
    theme: Literal['light', 'dark'] = 'light'


class StudioPolicyInput(BaseModel):
    allow_user_llm_config: bool
    global_provider_id: int | None = Field(default=None, gt=0)
    max_projects_per_user: int = Field(default=5, ge=1, strict=True)
    hosting_duration_hours: int = Field(default=1, ge=1, le=8760, strict=True)


class ProjectInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    brief: str = Field(min_length=12, max_length=12000)
    auto_mode: bool = False
    backend_mode: Literal['auto', 'static', 'fastapi'] = 'auto'
    source_format: Literal['single-file', 'multi-file'] = 'single-file'
    defer: bool = False


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    selection: dict | None = None
    defer: bool = False


class StageInput(BaseModel):
    feedback: str = ''
    defer: bool = False


class PublishInput(BaseModel):
    version: int | None = None


class VerificationInput(BaseModel):
    version: int | None = None
    include_optional: bool = False
    include_review: bool = False
    defer: bool = False
    selected_check_ids: list[str] | None = None


class ArchitectureInput(BaseModel):
    target_mode: Literal['static', 'fastapi']
    feedback: str = Field(default='', max_length=2000)
    defer: bool = False
