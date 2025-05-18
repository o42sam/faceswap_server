import stripe # Keep for now in case any old Stripe logic is referenced elsewhere, though new flows won't use it
import httpx # For Paystack API calls
import uuid as uuid_pkg # to avoid conflict with schema's uuid field

from fastapi import HTTPException, status, BackgroundTasks
from datetime import datetime, timedelta
from typing import Literal, Any

from app.core.config import settings
from app.models.user import User
from app.models.payment import PaymentAttempt
from app.repositories import payment as payment_repo, user as user_repo
from app.schemas.payment_schemas import (
    CreateCardPaymentRequest, PaystackInitializationResponse,
    CreateUSDTTransactionRequest, USDTTransactionResponse, PaymentStatusResponse
)
from app.utils.exceptions import PaymentError, NotFoundError, AppLogicError, InvalidInputError

# Stripe API Key (remains for potential other uses or legacy, but not for new card payments)
stripe.api_key = settings.STRIPE_SECRET_KEY


async def initialize_paystack_payment(
    user: User,
    payment_type: Literal["one_time", "monthly"],
    base_callback_url: str # Base URL for frontend callback e.g. https://frontend.com/payment
) -> PaystackInitializationResponse:
    if not settings.PAYSTACK_SECRET_KEY:
        raise AppLogicError(detail="Paystack not configured", error_code="PAYSTACK_NOT_CONFIGURED")

    amount_kobo = 0
    currency = "USD" # Paystack also supports NGN, GHS etc. Assuming USD for consistency with Stripe amounts
                     # If using NGN, ensure amounts are converted correctly.
                     # Paystack amounts are in smallest currency unit (kobo for NGN, cents for USD)
    
    description = ""

    if payment_type == "one_time":
        amount_kobo = settings.ONE_TIME_PAYMENT_AMOUNT_USD
        description = "One-Time Unlimited Access"
    elif payment_type == "monthly":
        amount_kobo = settings.MONTHLY_SUBSCRIPTION_AMOUNT_USD
        description = "Monthly Subscription"
    else:
        raise InvalidInputError(detail="Invalid payment type for Paystack", error_code="INVALID_PAYMENT_TYPE")

    reference = f"faceswap_{uuid_pkg.uuid4().hex}" # Unique reference for this transaction
    
    # The callback_url is where Paystack redirects the user after payment attempt.
    # Frontend should handle this URL, extract reference and call our verify endpoint.
    # Example: https://yourfrontend.com/paystack/callback
    callback_url = f"{base_callback_url.rstrip('/')}/paystack/callback"


    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": user.email,
        "amount": amount_kobo, # Amount in kobo/cents
        "currency": currency,
        "reference": reference,
        "callback_url": callback_url,
        "metadata": {
            "user_id": str(user.id),
            "payment_type": payment_type,
            "description": description,
            "internal_reference": reference # Store our unique ref here as well
        }
    }
    # For Paystack subscriptions, you'd typically create a Plan on Paystack
    # and then subscribe the customer to the plan_code.
    # This example handles it as a one-time or recurring payment managed by our app.

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{settings.PAYSTACK_API_URL}/transaction/initialize", headers=headers, json=payload)
            response.raise_for_status() # Will raise an exception for 4XX/5XX responses
            data = response.json()

        if not data.get("status"):
            raise PaymentError(detail=f"Paystack initialization failed: {data.get('message')}", error_code="PAYSTACK_INIT_FAILED")

        paystack_data = data.get("data", {})
        authorization_url = paystack_data.get("authorization_url")
        access_code = paystack_data.get("access_code")
        returned_reference = paystack_data.get("reference")

        if not all([authorization_url, access_code, returned_reference]):
            raise PaymentError(detail="Paystack initialization response missing crucial data.", error_code="PAYSTACK_INIT_INVALID_RESPONSE")

        # Create a pending payment attempt
        await payment_repo.create_payment_attempt(
            user=user,
            amount=float(amount_kobo / 100), # Store as dollars/main unit
            currency=currency.lower(),
            payment_method="card",
            payment_processor="paystack",
            transaction_id=returned_reference, # Use Paystack's reference as transaction_id
            status="pending", # User needs to complete action on Paystack's page
            metadata={
                "paystack_access_code": access_code,
                "payment_type": payment_type,
                "description": description
            }
        )
        
        return PaystackInitializationResponse(
            authorization_url=authorization_url,
            access_code=access_code,
            reference=returned_reference,
            publishable_key=settings.PAYSTACK_PUBLIC_KEY
        )
    except httpx.HTTPStatusError as e:
        error_detail = f"Paystack API error: {e.response.status_code} - {e.response.text}"
        try: # Try to parse Paystack's error message
            error_body = e.response.json()
            error_detail = f"Paystack API error: {error_body.get('message', e.response.text)}"
        except:
            pass # Stick with default error_detail
        raise PaymentError(detail=error_detail, error_code="PAYSTACK_API_ERROR")
    except Exception as e:
        raise AppLogicError(detail=f"Error initializing Paystack payment: {str(e)}", error_code="PAYSTACK_INIT_EXCEPTION")


async def verify_paystack_payment(reference: str, user: User) -> PaymentStatusResponse:
    if not settings.PAYSTACK_SECRET_KEY:
        raise AppLogicError(detail="Paystack not configured", error_code="PAYSTACK_NOT_CONFIGURED")

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
    }

    try:
        payment_attempt = await PaymentAttempt.find_one(
            PaymentAttempt.transaction_id == reference,
            PaymentAttempt.payment_processor == "paystack"
        )
        if not payment_attempt:
            raise NotFoundError(detail=f"Payment attempt with reference {reference} not found for Paystack.", error_code="PAYSTACK_PAYMENT_ATTEMPT_NOT_FOUND")
        
        # Ensure the payment attempt belongs to the current user, though reference should be unique enough
        # Be cautious if user is None for some verification flows (e.g. webhook)
        if user and payment_attempt.user.ref.id != user.id:
             raise AppLogicError(detail="Payment attempt does not belong to this user.", error_code="PAYSTACK_USER_MISMATCH")


        if payment_attempt.status == "succeeded":
             # If already successful, just return current status, don't re-verify unless necessary
            return await get_user_payment_status(await payment_attempt.user.fetch())


        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.PAYSTACK_API_URL}/transaction/verify/{reference}", headers=headers)
            response.raise_for_status()
            data = response.json()

        if not data.get("status"):
            await payment_repo.update_payment_attempt_status(payment_attempt, status="failed", metadata={"error": data.get("message", "Verification check failed")})
            raise PaymentError(detail=f"Paystack verification failed: {data.get('message')}", error_code="PAYSTACK_VERIFY_FAILED_API")

        paystack_tx_data = data.get("data", {})
        paystack_status = paystack_tx_data.get("status")
        
        # Ensure the user from metadata matches, if available
        tx_metadata = paystack_tx_data.get("metadata", {})
        metadata_user_id = tx_metadata.get("user_id")
        if user and metadata_user_id and str(user.id) != metadata_user_id:
            # This is a serious issue, potentially a mismatched reference or security concern
            await payment_repo.update_payment_attempt_status(payment_attempt, status="failed", metadata={"error": "User ID mismatch during verification"})
            raise PaymentError(detail="User ID in transaction metadata does not match current user.", error_code="PAYSTACK_VERIFY_USER_MISMATCH")

        payment_type = payment_attempt.metadata.get("payment_type") if payment_attempt.metadata else tx_metadata.get("payment_type")
        if not payment_type or payment_type not in ["one_time", "monthly"]:
            await payment_repo.update_payment_attempt_status(payment_attempt, status="failed", metadata={"error": "Invalid payment type in metadata"})
            raise PaymentError(detail="Invalid payment type in Paystack metadata", error_code="PAYSTACK_METADATA_INVALID")

        if paystack_status == "success":
            # Payment successful
            # Amount verification (Paystack returns amount in kobo/cents)
            amount_paid = paystack_tx_data.get("amount", 0)
            expected_amount_kobo_cents = 0
            if payment_type == "one_time":
                expected_amount_kobo_cents = settings.ONE_TIME_PAYMENT_AMOUNT_USD
            elif payment_type == "monthly":
                expected_amount_kobo_cents = settings.MONTHLY_SUBSCRIPTION_AMOUNT_USD
            
            if amount_paid < expected_amount_kobo_cents: # Check if amount paid is at least what was expected
                 await payment_repo.update_payment_attempt_status(
                    payment_attempt, 
                    status="failed", 
                    metadata={"error": f"Amount paid ({amount_paid}) less than expected ({expected_amount_kobo_cents})"}
                )
                 raise PaymentError(detail="Amount paid does not match expected amount.", error_code="PAYSTACK_AMOUNT_MISMATCH")

            await payment_repo.update_payment_attempt_status(
                payment_attempt, 
                status="succeeded",
                # transaction_id is already the reference. Can add Paystack's internal ID if needed.
                # metadata={"paystack_transaction_id": paystack_tx_data.get("id")} # Example
            )
            
            # Fetch the user associated with the payment attempt
            # This is important if 'user' param to this function could be different (e.g. system call)
            payment_user = await payment_attempt.user.fetch()

            await payment_repo.create_or_update_subscription(
                user=payment_user,
                subscription_type=payment_type, 
                status="active"
                # For Paystack managed subscriptions, you'd store paystack_tx_data.get("subscription_code")
            )
            return await get_user_payment_status(payment_user)
        
        elif paystack_status == "abandoned":
            await payment_repo.update_payment_attempt_status(payment_attempt, status="abandoned")
            raise PaymentError(detail="Paystack payment was abandoned.", error_code="PAYSTACK_PAYMENT_ABANDONED")
        else: # failed, pending, etc.
            await payment_repo.update_payment_attempt_status(payment_attempt, status="failed", metadata={"paystack_status": paystack_status})
            raise PaymentError(detail=f"Paystack payment not successful: {paystack_status}", error_code="PAYSTACK_PAYMENT_NOT_SUCCESSFUL")

    except httpx.HTTPStatusError as e:
        error_detail = f"Paystack API error during verification: {e.response.status_code} - {e.response.text}"
        try:
            error_body = e.response.json()
            error_detail = f"Paystack API error during verification: {error_body.get('message', e.response.text)}"
            # Update attempt based on API error if possible
            if payment_attempt and payment_attempt.status != "succeeded":
                 await payment_repo.update_payment_attempt_status(payment_attempt, status="failed", metadata={"error": error_detail})
        except:
            pass
        raise PaymentError(detail=error_detail, error_code="PAYSTACK_VERIFY_API_ERROR")
    except Exception as e:
        if payment_attempt and payment_attempt.status != "succeeded":
            await payment_repo.update_payment_attempt_status(payment_attempt, status="failed", metadata={"error": str(e)})
        raise AppLogicError(detail=f"Error verifying Paystack payment: {str(e)}", error_code="PAYSTACK_VERIFICATION_EXCEPTION")


# --- USDT and common functions remain largely unchanged ---
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

    payment_attempt = await payment_repo.create_payment_attempt(
        user=user,
        amount=expected_amount_usd,
        currency="usdt", 
        payment_method="usdt",
        status="pending", 
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
    payment_attempt_id: uuid_pkg.UUID, # Renamed to avoid conflict
    transaction_hash: str,
    background_tasks: BackgroundTasks
) -> PaymentStatusResponse:
    payment_attempt = await payment_repo.get_payment_attempt(payment_attempt_id)
    if not payment_attempt or payment_attempt.user.ref.id != user.id:
        raise NotFoundError(detail="Payment attempt not found or does not belong to user", error_code="USDT_PAYMENT_ATTEMPT_NOT_FOUND")
    
    if payment_attempt.status == "succeeded":
        raise AppLogicError(detail="This payment has already been confirmed.", error_code="USDT_ALREADY_CONFIRMED")
    if payment_attempt.status == "failed":
        raise PaymentError(detail="This payment attempt was previously marked as failed.", error_code="USDT_PAYMENT_FAILED_PREVIOUSLY")

    # Basic validation of transaction_hash format (moved from endpoint to service)
    if not transaction_hash.startswith("0x") or len(transaction_hash) != 66:
        raise InvalidInputError(detail="Invalid transaction hash format.", error_code="INVALID_TX_HASH")

    payment_attempt.transaction_id = transaction_hash # Store blockchain hash
    payment_attempt.status = "pending" # Mark as pending verification (can also be 'requires_action')
    await payment_attempt.save()
    
    # SIMULATED SUCCESS (as before)
    payment_type = payment_attempt.metadata.get("payment_type") if payment_attempt.metadata else None
    if not payment_type or payment_type not in ["one_time", "monthly"]:
        await payment_repo.update_payment_attempt_status(payment_attempt, status="failed", metadata={"error": "Invalid payment type in metadata"})
        raise PaymentError(detail="Invalid payment type in payment attempt metadata", error_code="USDT_METADATA_INVALID")

    await payment_repo.update_payment_attempt_status(payment_attempt, status="succeeded", transaction_id=transaction_hash)
    await payment_repo.create_or_update_subscription(
        user=user,
        subscription_type=payment_type,
        status="active"
    )
    return await get_user_payment_status(user)


async def get_user_payment_status(user: User) -> PaymentStatusResponse:
    # Ensure user object has subscription details potentially fetched/updated
    # This might involve reloading the user or ensuring links are fetched if subscription is a separate doc
    # For this example, we assume user object passed is up-to-date after payment operations.
    # However, if User.subscription_id is a Link, it needs to be fetched.
    # The User model in snippet does not show subscription_id as a Link, but fields like
    # user.subscription_type, user.subscription_start_date, user.subscription_end_date
    # These are assumed to be updated by `create_or_update_subscription` in `payment`.

    # Let's ensure user object is fresh if it's been modified in DB by other functions
    await user.reload() 

    is_active_subscriber = False
    requests_remaining = None
    sub_end_date_str = None
    message = "User is on the free tier or subscription has expired."
    current_time = datetime.utcnow()

    if user.subscription_type == "one_time":
        # Check if start_date exists, implying a successful one-time purchase
        if user.subscription_start_date: # A one-time purchase should have a start date
            is_active_subscriber = True
            requests_remaining = None # Unlimited
            message = "User has a one-time unlimited access subscription."
        else: # Never actually made a one-time payment
            user.subscription_type = "none" 
            # Fall through to free tier logic

    if user.subscription_type == "monthly": # Changed from elif to if to allow falling from failed one_time
        if user.subscription_end_date and user.subscription_end_date > current_time:
            is_active_subscriber = True
            
            # Reset monthly count if new billing cycle started
            # This logic might be better in a periodic task or upon first request of new cycle
            if user.subscription_start_date and user.last_request_date:
                # Approximate check: if last request was before current cycle's start
                current_cycle_start_date = user.subscription_end_date - timedelta(days=30) # Approximation
                if user.last_request_date < current_cycle_start_date:
                    if user.monthly_requests_used > 0:
                        await user.reset_monthly_user_request_count(user.id) # Assuming user takes user_id
                        await user.reload() # refresh user data

            requests_remaining = settings.MONTHLY_REQUEST_LIMIT - user.monthly_requests_used
            sub_end_date_str = user.subscription_end_date.isoformat()
            message = f"User has an active monthly subscription. Requests remaining: {requests_remaining}."
        elif user.subscription_end_date and user.subscription_end_date <= current_time:
            message = "User's monthly subscription has expired."
            # user.subscription_type = "none" # Or "expired"
            # await user.save() # Persist this change
            # Fall through to free tier logic if subscription expired

    if not is_active_subscriber: # Handles free tier, expired, or never subscribed
        # If user type became 'none' from expired or failed one_time, reset it for free tier message.
        # Or ensure user.subscription_type reflects an 'expired' state distinctly.
        # For simplicity, if not active, they are on 'free tier' equivalent for request counting.
        
        requests_remaining = settings.FREE_REQUEST_LIMIT - user.free_requests_used
        message = f"User is on the free tier. Free requests remaining: {max(0, requests_remaining)}."
        if requests_remaining <=0:
            message = f"User has used all free requests. Please subscribe."
        
        # This part seems to manage a specific 'free_tier_used' status on the user model.
        # If the user was previously 'monthly' or 'one_time' but is no longer active,
        # they revert to free tier logic. The 'free_tier_used' status indicates they've
        # exhausted free tier AND were never subscribed, or their subscription fully lapsed.
        # This might need refinement based on exact desired UX for lapsed subscribers vs new free users.
        # For now, if they aren't an active subscriber and have no free requests, update status if they are 'none'.
        if requests_remaining <= 0 and user.subscription_type == "none":
            user.subscription_type = "free_tier_used" # Mark that free tier is exhausted
            await user.save()


    return PaymentStatusResponse(
        user_id=user.id,
        subscription_type=str(user.subscription_type), # Ensure it's a string
        is_active_subscriber=is_active_subscriber,
        requests_remaining=requests_remaining,
        subscription_end_date=sub_end_date_str,
        message=message
    )

# Placeholder for Stripe functions if needed for other reasons (e.g. webhook handling for existing Stripe subs)
# For this task, they are not called for new card payments.
async def create_stripe_checkout_session(*args, **kwargs):
    raise NotImplementedError("Stripe checkout is deprecated. Use Paystack.")

async def verify_stripe_payment(*args, **kwargs):
    raise NotImplementedError("Stripe verification is deprecated. Use Paystack.")