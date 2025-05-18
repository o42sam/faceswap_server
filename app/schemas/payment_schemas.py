from pydantic import BaseModel, Field
from typing import Literal, Optional
import uuid

class CreateCardPaymentRequest(BaseModel): # Renamed from CreateCheckoutSessionRequest for clarity
    payment_type: Literal["one_time", "monthly"]

# Renamed from StripeCheckoutSessionResponse
class PaystackInitializationResponse(BaseModel):
    authorization_url: str
    access_code: str
    reference: str
    publishable_key: Optional[str] = None # Paystack public key, send if frontend needs it (e.g. for Paystack JS)

class CreateUSDTTransactionRequest(BaseModel):
    payment_type: Literal["one_time", "monthly"]
    # Removed transaction_hash from here, as it's for confirmation step

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