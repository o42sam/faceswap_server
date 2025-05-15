from pydantic import BaseModel
from typing import Optional
import uuid

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

class TokenPayload(BaseModel):
    sub: Optional[uuid.UUID] = None
    type: Optional[str] = None # "access" or "refresh"
    exp: Optional[int] = None