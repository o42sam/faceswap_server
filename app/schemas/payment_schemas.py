from pydantic import BaseModel, Field
from typing import Literal, Optional
import uuid

class CreateCheckoutSessionRequest(BaseModel):
    payment_type: Literal["one_time", "monthly"]

class StripeCheckoutSessionResponse(BaseModel):
    session_id: str
    publishable_key: str
    url: Optional[str] = None # For Stripe Checkout redirect

class CreateUSDTTransactionRequest(BaseModel):
    payment_type: Literal["one_time", "monthly"]
    transaction_hash: str # User provides this after sending USDT

class USDTTransactionResponse(BaseModel):
    message: str
    payment_attempt_id: uuid.UUID
    wallet_address: str
    expected_amount_usd: float
    payment_type: Literal["one_time", "monthly"]

class PaymentStatusResponse(BaseModel):
    user_id: uuid.UUID
    subscription_type: str
    is_active_subscriber: bool
    requests_remaining: Optional[int] = None # null for one-time or if unlimited
    subscription_end_date: Optional[str] = None
    message: str