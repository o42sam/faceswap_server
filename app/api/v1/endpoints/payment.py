from fastapi import APIRouter, Depends, Request, BackgroundTasks, Query
from typing import Annotated

from app.models.user import User
from app.core.dependencies import get_current_active_user
from app.services import payment_service
from app.schemas.payment_schemas import (
    CreateCheckoutSessionRequest, StripeCheckoutSessionResponse,
    CreateUSDTTransactionRequest, USDTTransactionResponse, PaymentStatusResponse
)
from app.utils.custom_exceptions import AppLogicError

router = APIRouter()

@router.post("/stripe/create-checkout-session", response_model=StripeCheckoutSessionResponse)
async def create_stripe_checkout(
    payload: CreateCheckoutSessionRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    request: Request # Needed for success/cancel URLs if dynamically generated
):
    # Frontend should provide these URLs, or construct them based on request.base_url
    # For this example, let's assume they are passed or configured
    base_url = str(request.base_url).rstrip('/')
    success_url = f"{base_url}/payment-success" # Placeholder
    cancel_url = f"{base_url}/payment-cancel"   # Placeholder
    
    return await payment_service.create_stripe_checkout_session(
        user=current_user,
        payment_type=payload.payment_type,
        success_url=success_url,
        cancel_url=cancel_url
    )

@router.get("/stripe/verify-payment", response_model=PaymentStatusResponse)
async def verify_stripe_payment_endpoint(
    session_id: str = Query(..., description="Stripe Checkout Session ID"),
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    return await payment_service.verify_stripe_payment(session_id=session_id, user=current_user)


@router.post("/usdt/initiate-payment", response_model=USDTTransactionResponse)
async def initiate_usdt_payment_endpoint(
    payload: CreateUSDTTransactionRequest, # Only payment_type needed here
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    return await payment_service.initiate_usdt_payment(user=current_user, payment_type=payload.payment_type)

@router.post("/usdt/confirm-payment", response_model=PaymentStatusResponse)
async def confirm_usdt_payment_endpoint(
    payment_attempt_id: uuid.UUID = Query(..., description="Internal payment attempt ID"),
    transaction_hash: str = Query(..., description="USDT transaction hash from the blockchain"),
    current_user: Annotated[User, Depends(get_current_active_user)],
    background_tasks: BackgroundTasks
):
    # Basic validation of transaction_hash format could be added
    if not transaction_hash.startswith("0x") or len(transaction_hash) != 66:
        raise AppLogicError(detail="Invalid transaction hash format.", error_code="INVALID_TX_HASH")
        
    return await payment_service.confirm_usdt_payment(
        user=current_user,
        payment_attempt_id=payment_attempt_id,
        transaction_hash=transaction_hash,
        background_tasks=background_tasks
    )

@router.get("/status", response_model=PaymentStatusResponse)
async def get_payment_status_endpoint(current_user: Annotated[User, Depends(get_current_active_user)]):
    return await payment_service.get_user_payment_status(user=current_user)