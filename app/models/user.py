from typing import Optional, Literal, Annotated
from beanie import Document, Indexed # Indexed might be unused if all fields are changed
from pydantic import EmailStr, Field
import uuid
from datetime import datetime

class User(Document):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    # Changed to use Field for unique index definition
    email: EmailStr = Field(unique=True)
    hashed_password: Optional[str] = None
    full_name: Optional[str] = None
    is_active: bool = True
    is_superuser: bool = False
    # This line, as provided in your file, is already correctly defined using Field
    # to avoid the error mentioned in the traceback.
    # The traceback indicated an erroneous line: Optional[Annotated[str, Indexed(unique=True, sparse=True)]]
    # The corrected form (and current form in your file) is:
    google_id: Optional[str] = Field(default=None, unique=True, sparse=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    subscription_type: Literal["none", "free_tier_used", "monthly", "one_time"] = "none"
    subscription_id: Optional[str] = None # Stripe subscription ID or internal ID
    subscription_start_date: Optional[datetime] = None
    subscription_end_date: Optional[datetime] = None # For monthly subscriptions

    free_requests_used: int = 0
    monthly_requests_used: int = 0 # Resets monthly for "monthly" subscribers
    last_request_date: Optional[datetime] = None

    class Settings:
        name = "users"
        keep_nulls = False # Important for sparse indexes like google_id

    async def before_save(self):
        self.updated_at = datetime.utcnow()