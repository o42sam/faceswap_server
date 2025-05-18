import uuid
from datetime import datetime

from app.models.user import User
from app.models.payment import PaymentAttempt, Subscription
from app.schemas.payment_schemas import CreateUSDTTransactionRequest
from app.core.config import settings
from typing import Optional, Literal, Union

async def create_payment_attempt(
    user: User,
    amount: float,
    currency: str,
    payment_method: Literal["card", "usdt"],
    payment_processor: Optional[str] = None,
    transaction_id: Optional[str] = None,
    status: Literal["pending", "succeeded", "failed", "requires_action"] = "pending",
    metadata: Optional[dict] = None,
) -> PaymentAttempt:
    payment = PaymentAttempt(
        user=user.to_ref(),
        amount=amount,
        currency=currency,
        payment_method=payment_method,
        payment_processor=payment_processor,
        transaction_id=transaction_id,
        status=status,
        metadata=metadata,
    )
    await payment.insert()
    return payment

async def get_payment_attempt(payment_attempt_id: uuid.UUID) -> Optional[PaymentAttempt]:
    return await PaymentAttempt.get(payment_attempt_id)

async def update_payment_attempt_status(
    payment_attempt: PaymentAttempt,
    status: Literal["pending", "succeeded", "failed", "requires_action"],
    transaction_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> PaymentAttempt:
    payment_attempt.status = status
    if transaction_id:
        payment_attempt.transaction_id = transaction_id
    if metadata:
        payment_attempt.metadata = metadata if payment_attempt.metadata is None else {**payment_attempt.metadata, **metadata}
    await payment_attempt.save()
    return payment_attempt


async def create_or_update_subscription(
    user: User,
    subscription_type: Literal["monthly", "one_time"],
    payment_processor_subscription_id: Optional[str] = None, # For Stripe
    status: Literal["active", "inactive", "cancelled", "past_due"] = "active",
    start_date: datetime = datetime.utcnow(),
    end_date: Optional[datetime] = None, # Calculated based on type
) -> Subscription:
    
    existing_subscription = await Subscription.find_one(Subscription.user.id == user.id)

    if subscription_type == "monthly":
        end_date = start_date + timedelta(days=30) # Simple 30 day cycle
    elif subscription_type == "one_time":
        end_date = None # Or a very far future date if preferred

    if existing_subscription:
        subscription = existing_subscription
        subscription.subscription_type = subscription_type
        subscription.payment_processor_subscription_id = payment_processor_subscription_id if payment_processor_subscription_id else subscription.payment_processor_subscription_id
        subscription.status = status
        subscription.start_date = start_date
        subscription.end_date = end_date
        subscription.last_payment_date = start_date
    else:
        subscription = Subscription(
            user=user.to_ref(),
            subscription_type=subscription_type,
            payment_processor_subscription_id=payment_processor_subscription_id,
            status=status,
            start_date=start_date,
            end_date=end_date,
            last_payment_date=start_date
        )
    
    await subscription.save()

    user.subscription_type = subscription_type
    user.subscription_id = str(subscription.id)
    user.subscription_start_date = start_date
    user.subscription_end_date = end_date
    if subscription_type == "monthly": # Reset monthly count on new/updated monthly sub
        user.monthly_requests_used = 0
    await user.save()
    
    return subscription

async def get_user_subscription(user: User) -> Optional[Subscription]:
    return await Subscription.find_one(Subscription.user.id == user.id)