from typing import Literal
from pydantic import BaseModel, Field, EmailStr


class RegisterInput(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=128)


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str


class ProviderInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    base_url: str = 'https://api.openai.com/v1'
    model: str = Field(min_length=1, max_length=120)
    api_key: str = ''
    enabled: bool = True


class PreferenceInput(BaseModel):
    provider_id: int | None = None
    auto_mode: bool = False
    theme: Literal['light', 'dark'] = 'light'


class ProjectInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    brief: str = Field(min_length=12, max_length=12000)
    auto_mode: bool = False
    backend_mode: Literal['auto', 'static', 'fastapi'] = 'auto'
    defer: bool = False


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    selection: dict | None = None


class StageInput(BaseModel):
    feedback: str = ''


class PublishInput(BaseModel):
    version: int | None = None
