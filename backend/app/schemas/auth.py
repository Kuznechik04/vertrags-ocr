from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas._common import UtcDatetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: str
    created_at: UtcDatetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
