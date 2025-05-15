import stripe
from fastapi import HTTPException, status, BackgroundTasks
from datetime import datetime, timedelta
from typing import Literal

from app.core.config import settings
from app.models.user import User
from app.models.payment import PaymentAttempt
from app.crud import crud_payment, crud_user
from app.schemas.payment_schemas import CreateCheckoutSessionRequest, StripeCheckoutSessionResponse, CreateUSDTTransactionRequest, USDTTransactionResponse, PaymentStatusResponse
from app.utils.custom_exceptions import PaymentError, NotFoundError, AppLogicError, InvalidInputError

stripe.api_key = settings.STRIPE_SECRET_KEY

async def create_stripe_checkout_session(
    user: User,
    payment_type: Literal["one_time", "monthly"],
    success_url: str, # Should come from frontend
    cancel_url: str   # Should come from frontend
) -> StripeCheckoutSessionResponse:
    if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_PUBLISHABLE_KEY:
        raise AppLogicError(detail="Stripe not configured", error_code="STRIPE_NOT_CONFIGURED")

    line_items = []
    mode: Literal["payment", "subscription"] = "payment"
    metadata = {"user_id": str(user.id), "payment_type": payment_type}

    if payment_type == "one_time":
        amount = settings.ONE_TIME_PAYMENT_AMOUNT_USD
        name = "One-Time Unlimited Access"
        mode = "payment"
        line_items = [{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": name},
                "unit_amount": amount,
            },
            "quantity": 1,
        }]
    elif payment_type == "monthly":
        amount = settings.MONTHLY_SUBSCRIPTION_AMOUNT_USD
        name = "Monthly Subscription"
        mode = "subscription"
        line_items = [{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": name},
                "unit_amount": amount,
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }]
        # For subscriptions, it's better to create a Product and Price in Stripe dashboard
        # and use the Price ID here: e.g., "price": "price_1abc..."
    else:
        raise InvalidInputError(detail="Invalid payment type for Stripe checkout", error_code="INVALID_PAYMENT_TYPE")

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode=mode,
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}", # Append session_id for frontend to verify
            cancel_url=cancel_url,
            customer_email=user.email, # Pre-fill email
            metadata=metadata,
            # For subscriptions, you might want to manage customers:
            # customer_creation="if_required", # or pass existing customer ID
        )
        
        # Create a pending payment attempt
        await crud_payment.create_payment_attempt(
            user=user,
            amount=float(amount / 100),
            currency="usd",
            payment_method="card",
            payment_processor="stripe",
            status="requires_action", # as user needs to complete checkout
            metadata={"stripe_session_id": checkout_session.id, "payment_type": payment_type}
        )
        
        return StripeCheckoutSessionResponse(
            session_id=checkout_session.id, 
            publishable_key=settings.STRIPE_PUBLISHABLE_KEY,
            url=checkout_session.url
        )
    except stripe.error.StripeError as e:
        raise PaymentError(detail=f"Stripe error: {str(e)}", error_code="STRIPE_API_ERROR")
    except Exception as e:
        raise AppLogicError(detail=f"Error creating Stripe session: {str(e)}", error_code="STRIPE_SESSION_CREATION_FAILED")


async def verify_stripe_payment(session_id: str, user: User) -> PaymentStatusResponse:
    if not settings.STRIPE_SECRET_KEY:
        raise AppLogicError(detail="Stripe not configured", error_code="STRIPE_NOT_CONFIGURED")
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        payment_intent_id = None
        subscription_id_stripe = None

        if session.payment_status == "paid" or (session.mode == "subscription" and session.status == "complete"):
            
            if session.mode == "payment": # One-time
                payment_intent_id = session.payment_intent
            elif session.mode == "subscription": # Monthly
                subscription_id_stripe = session.subscription
            
            payment_type = session.metadata.get("payment_type")
            if not payment_type or payment_type not in ["one_time", "monthly"]:
                raise PaymentError(detail="Invalid payment type in Stripe metadata", error_code="STRIPE_METADATA_INVALID")

            payment_attempt = await PaymentAttempt.find_one(PaymentAttempt.metadata.stripe_session_id == session_id)
            if not payment_attempt:
                 await crud_payment.create_payment_attempt(
                    user=user,
                    amount=float(session.amount_total / 100) if session.amount_total else 0.0,
                    currency=session.currency,
                    payment_method="card",
                    payment_processor="stripe",
                    transaction_id=payment_intent_id or subscription_id_stripe,
                    status="succeeded",
                    metadata={"stripe_session_id": session_id, "payment_type": payment_type}
                )
            elif payment_attempt.status != "succeeded":
                 await crud_payment.update_payment_attempt_status(
                    payment_attempt, 
                    status="succeeded", 
                    transaction_id=payment_intent_id or subscription_id_stripe
                )
            
            await crud_payment.create_or_update_subscription(
                user=user,
                subscription_type=payment_type,
                payment_processor_subscription_id=subscription_id_stripe,
                status="active"
            )
            return await get_user_payment_status(user)
        
        elif session.status == "open": # Still in progress
             raise PaymentError(detail="Payment is still pending completion.", error_code="STRIPE_PAYMENT_PENDING", status_code=status.HTTP_402_PAYMENT_REQUIRED)
        else: # expired, failed etc.
            payment_attempt = await PaymentAttempt.find_one(PaymentAttempt.metadata.stripe_session_id == session_id)
            if payment_attempt and payment_attempt.status != "failed":
                 await crud_payment.update_payment_attempt_status(payment_attempt, status="failed")
            raise PaymentError(detail=f"Stripe payment not successful: {session.status}", error_code="STRIPE_PAYMENT_FAILED")

    except stripe.error.StripeError as e:
        raise PaymentError(detail=f"Stripe error verifying payment: {str(e)}", error_code="STRIPE_VERIFICATION_ERROR")
    except Exception as e:
        raise AppLogicError(detail=f"Error verifying Stripe payment: {str(e)}", error_code="STRIPE_VERIFICATION_FAILED")


async def initiate_usdt_payment(user: User, payment_type: Literal["one_time", "monthly"]) -> USDTTransactionResponse:
    if not settings.USDT_ETH_WALLET_ADDRESS:
        raise AppLogicError(detail="USDT payment not configured", error_code="USDT_NOT_CONFIGURED")

    expected_amount_usd = 0.0
    if payment_type == "one_time":
        expected_amount_usd = float(settings.ONE_TIME_PAYMENT_AMOUNT_USD / 100)
    elif payment_type == "monthly":
        expected_amount_usd = float(settings.MONTHLY_SUBSCRIPTION_AMOUNT_USD / 100)
    else:
        raise InvalidInputError(detail="Invalid payment type for USDT payment", error_code="INVALID_PAYMENT_TYPE")

    # Create a pending payment attempt
    payment_attempt = await crud_payment.create_payment_attempt(
        user=user,
        amount=expected_amount_usd,
        currency="usdt", # Assuming USDT amount will be equivalent to USD price
        payment_method="usdt",
        status="pending", # User needs to make the transfer and provide hash
        metadata={"payment_type": payment_type, "expected_usd_value": expected_amount_usd}
    )

    return USDTTransactionResponse(
        message="Please send the equivalent USDT (ERC20) amount to the provided wallet address. "
                "After sending, submit the transaction hash to confirm.",
        payment_attempt_id=payment_attempt.id,
        wallet_address=settings.USDT_ETH_WALLET_ADDRESS,
        expected_amount_usd=expected_amount_usd,
        payment_type=payment_type
    )

async def confirm_usdt_payment(
    user: User,
    payment_attempt_id: uuid.UUID,
    transaction_hash: str,
    background_tasks: BackgroundTasks
) -> PaymentStatusResponse:
    payment_attempt = await crud_payment.get_payment_attempt(payment_attempt_id)
    if not payment_attempt or payment_attempt.user.ref.id != user.id:
        raise NotFoundError(detail="Payment attempt not found or does not belong to user", error_code="USDT_PAYMENT_ATTEMPT_NOT_FOUND")
    
    if payment_attempt.status == "succeeded":
        raise AppLogicError(detail="This payment has already been confirmed.", error_code="USDT_ALREADY_CONFIRMED")
    if payment_attempt.status == "failed":
        raise PaymentError(detail="This payment attempt was previously marked as failed.", error_code="USDT_PAYMENT_FAILED_PREVIOUSLY")

    payment_attempt.transaction_id = transaction_hash
    payment_attempt.status = "pending" # Mark as pending verification
    await payment_attempt.save()

    # Placeholder for actual blockchain verification
    # In a real scenario, you'd have a background task to query a blockchain explorer API
    # For now, we'll simulate success after a short delay or assume manual verification
    # For this example, let's assume it's successful and update immediately.
    # TODO: Implement actual blockchain verification logic (e.g., using Etherscan API)
    # background_tasks.add_task(verify_usdt_transaction_on_blockchain, payment_attempt_id, transaction_hash)
    
    # --- SIMULATED SUCCESS ---
    payment_type = payment_attempt.metadata.get("payment_type")
    if not payment_type or payment_type not in ["one_time", "monthly"]:
        await crud_payment.update_payment_attempt_status(payment_attempt, status="failed", metadata={"error": "Invalid payment type in metadata"})
        raise PaymentError(detail="Invalid payment type in payment attempt metadata", error_code="USDT_METADATA_INVALID")

    await crud_payment.update_payment_attempt_status(payment_attempt, status="succeeded", transaction_id=transaction_hash)
    await crud_payment.create_or_update_subscription(
        user=user,
        subscription_type=payment_type,
        status="active"
    )
    # --- END SIMULATED SUCCESS ---

    return await get_user_payment_status(user)

async def get_user_payment_status(user: User) -> PaymentStatusResponse:
    await user.fetch_link(User.subscription_id) # if subscription_id is a Link to Subscription model
    
    is_active_subscriber = False
    requests_remaining = None
    sub_end_date_str = None
    message = "User is on the free tier or subscription has expired."

    current_time = datetime.utcnow()

    if user.subscription_type == "one_time":
        is_active_subscriber = True
        requests_remaining = None # Unlimited
        message = "User has a one-time unlimited access subscription."
    elif user.subscription_type == "monthly" and user.subscription_end_date and user.subscription_end_date > current_time:
        is_active_subscriber = True
        # Check and reset monthly count if new month started
        if user.subscription_start_date and user.subscription_end_date:
             # A simple way to check if a new billing cycle has started since last request or subscription update
            if user.last_request_date and user.last_request_date < (user.subscription_end_date - timedelta(days=30)): # Approximation
                 if user.monthly_requests_used > 0: # If it's a new cycle and some requests were used
                    await crud_user.reset_monthly_user_request_count(user)
                    await user.reload() # refresh user data

        requests_remaining = settings.MONTHLY_REQUEST_LIMIT - user.monthly_requests_used
        sub_end_date_str = user.subscription_end_date.isoformat()
        message = f"User has an active monthly subscription. Requests remaining: {requests_remaining}."
    elif user.subscription_type == "monthly" and user.subscription_end_date and user.subscription_end_date <= current_time:
        message = "User's monthly subscription has expired."
        # Optionally change user.subscription_type to "none" or "expired" here or via a cron job
    
    if not is_active_subscriber:
        requests_remaining = settings.FREE_REQUEST_LIMIT - user.free_requests_used
        message = f"User is on the free tier. Free requests remaining: {requests_remaining}."
        if requests_remaining <=0:
            message = f"User has used all free requests. Please subscribe."
            if user.subscription_type == "none": # If they were never on free_tier_used
                user.subscription_type = "free_tier_used"
                await user.save()


    return PaymentStatusResponse(
        user_id=user.id,
        subscription_type=user.subscription_type,
        is_active_subscriber=is_active_subscriber,
        requests_remaining=requests_remaining,
        subscription_end_date=sub_end_date_str,
        message=message
    )

# Placeholder for actual blockchain verification (would run in background)
async def verify_usdt_transaction_on_blockchain(payment_attempt_id: uuid.UUID, transaction_hash: str):
    # 1. Get payment_attempt from DB
    # 2. Use an API (e.g., Etherscan, Infura) to check the transaction_hash
    #    - Check if transaction exists
    #    - Check if 'to' address matches settings.USDT_ETH_WALLET_ADDRESS
    #    - Check if 'value' (amount of USDT) is correct (may need USDT price oracle for USD equivalent)
    #    - Check if transaction is confirmed (sufficient block confirmations)
    # 3. If all good:
    #    - Update payment_attempt status to "succeeded"
    #    - Call crud_payment.create_or_update_subscription
    # 4. If not good:
    #    - Update payment_attempt status to "failed" with error details
    print(f"Background task: Verifying USDT transaction {transaction_hash} for attempt {payment_attempt_id}")
    # ... implementation ...
    pass