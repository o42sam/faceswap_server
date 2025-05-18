from beanie import Document, Link
from pydantic import Field
from typing import Optional, Literal
from datetime import datetime
import uuid
from app.models.user import User

class PaymentAttempt(Document):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    user: Link[User]
    amount: float
    currency: str # e.g., "usd", "usdt", "ngn"
    payment_method: Literal["card", "usdt"]
    payment_processor: Optional[Literal["stripe", "paystack"]] = None # e.g., "stripe", "paystack"
    transaction_id: Optional[str] = None # From payment processor (e.g. Paystack reference) or blockchain
    status: Literal["pending", "succeeded", "failed", "requires_action", "abandoned"] = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Optional[dict] = None # e.g., Stripe payment intent ID, Paystack access_code, error messages

    class Settings:
        name = "payment_attempts"

    async def before_save(self):
        self.updated_at = datetime.utcnow()

class Subscription(Document):
    id: uuid.UUID = Field(default_factory=uuid.uuid4) # Internal ID
    user: Link[User]
    subscription_type: Literal["monthly", "one_time"]
    payment_processor_subscription_id: Optional[str] = None # e.g., Stripe subscription ID, or Paystack plan/sub ID if used
    status: Literal["active", "inactive", "cancelled", "past_due"] = "inactive"
    start_date: datetime
    end_date: Optional[datetime] = None # For monthly, this is the next renewal date. For one-time, can be null or far future.
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_payment_date: Optional[datetime] = None
    
    class Settings:
        name = "subscriptions"

    async def before_save(self):
        self.updated_at = datetime.utcnow()