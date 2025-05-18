from fastapi import APIRouter, Depends, Request, BackgroundTasks, Query
from typing import Annotated
import uuid # Standard Python UUID

from app.models.user import User
from app.core.dependencies import get_current_active_user
from app.services import payment # payment will now have paystack functions
from app.schemas.payment_schemas import (
    CreateCardPaymentRequest, PaystackInitializationResponse, # Changed Stripe to Paystack
    CreateUSDTTransactionRequest, USDTTransactionResponse, PaymentStatusResponse
)
from app.utils.exceptions import AppLogicError

router = APIRouter()

@router.post("/paystack/initialize-payment", response_model=PaystackInitializationResponse)
async def initialize_paystack_checkout( # Renamed from create_stripe_checkout
    payload: CreateCardPaymentRequest, # Reusing schema, name changed for clarity
    current_user: Annotated[User, Depends(get_current_active_user)],
    request: Request
):
    # The callback URL for Paystack is set within the service layer.
    # Frontend will provide a base for its own callback page.
    # e.g. if frontend is at https://app.example.com, it might use
    # https://app.example.com/payment as base_callback_url
    # and Paystack will be configured to redirect to https://app.example.com/payment/paystack/callback

    # For this example, we'll use request.base_url for the frontend base callback.
    # In a real app, frontend might send its specific base callback URL.
    base_frontend_callback_url = str(request.base_url).rstrip('/')

    return await payment.initialize_paystack_payment(
        user=current_user,
        payment_type=payload.payment_type,
        base_callback_url=base_frontend_callback_url # This is the base URL for the frontend page that handles Paystack callback
    )

@router.get("/paystack/verify-payment", response_model=PaymentStatusResponse)
async def verify_paystack_payment_endpoint( # Renamed from verify_stripe_payment_endpoint
    current_user: Annotated[User, Depends(get_current_active_user)], # Moved before 'reference'
    reference: str = Query(..., description="Paystack Transaction Reference") # Changed from session_id
):
    return await payment.verify_paystack_payment(reference=reference, user=current_user)


# USDT Endpoints remain unchanged
@router.post("/usdt/initiate-payment", response_model=USDTTransactionResponse)
async def initiate_usdt_payment_endpoint(
    payload: CreateUSDTTransactionRequest,
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    return await payment.initiate_usdt_payment(user=current_user, payment_type=payload.payment_type)

@router.post("/usdt/confirm-payment", response_model=PaymentStatusResponse)
async def confirm_usdt_payment_endpoint(
    current_user: Annotated[User, Depends(get_current_active_user)], # Moved before parameters with defaults
    background_tasks: BackgroundTasks, # Moved before parameters with defaults
    payment_attempt_id: uuid.UUID = Query(..., description="Internal payment attempt ID"),
    transaction_hash: str = Query(..., description="USDT transaction hash from the blockchain")
):
    # Validation of transaction_hash format is now in the service layer
    return await payment.confirm_usdt_payment(
        user=current_user,
        payment_attempt_id=payment_attempt_id,
        transaction_hash=transaction_hash,
        background_tasks=background_tasks
    )

@router.get("/status", response_model=PaymentStatusResponse)
async def get_payment_status_endpoint(current_user: Annotated[User, Depends(get_current_active_user)]):
    return await payment.get_user_payment_status(user=current_user)