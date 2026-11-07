from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterRequest(StrictModel):
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=10, max_length=128)


class LoginRequest(StrictModel):
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)


class RefreshRequest(StrictModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class PasswordChangeRequest(StrictModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=10, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    message: str
