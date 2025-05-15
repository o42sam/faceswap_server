from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
import uuid
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None

class UserCreate(UserBase):
    password: str = Field(min_length=8)

class UserCreateGoogle(UserBase):
    google_id: str

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=8)

class UserResponse(UserBase):
    id: uuid.UUID
    is_active: bool
    is_superuser: bool
    subscription_type: str
    free_requests_used: int
    monthly_requests_used: int
    subscription_end_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    email: EmailStr
    password: str