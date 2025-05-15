import uuid
from datetime import datetime, timedelta

from app.models.user import User
from app.models.payment import PaymentAttempt, Subscription
from app.core.security import get_password_hash
from app.core.config import settings


def create_mock_user(
    email="testuser@example.com",
    password="password123",
    full_name="Test User",
    is_active=True,
    is_superuser=False,
    google_id=None,
    subscription_type="none",
    free_requests_used=0,
    monthly_requests_used=0,
    subscription_end_date=None,
    user_id=None
) -> User:
    if user_id is None:
        user_id = uuid.uuid4()
    
    hashed_password = get_password_hash(password) if password else None
    
    return User(
        id=user_id,
        email=email,
        hashed_password=hashed_password,
        full_name=full_name,
        is_active=is_active,
        is_superuser=is_superuser,
        google_id=google_id,
        subscription_type=subscription_type,
        free_requests_used=free_requests_used,
        monthly_requests_used=monthly_requests_used,
        subscription_end_date=subscription_end_date,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

def create_mock_payment_attempt(
    user: User,
    amount=29.99,
    currency="usd",
    payment_method="card",
    status="succeeded",
    metadata=None
) -> PaymentAttempt:
    if metadata is None:
        metadata = {"stripe_session_id": f"cs_test_{uuid.uuid4()}"}
    return PaymentAttempt(
        id=uuid.uuid4(),
        user=user.to_ref(),
        amount=amount,
        currency=currency,
        payment_method=payment_method,
        status=status,
        metadata=metadata,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

def create_mock_subscription(
    user: User,
    subscription_type="one_time",
    status="active"
) -> Subscription:
    start_date = datetime.utcnow()
    end_date = None
    if subscription_type == "monthly":
        end_date = start_date + timedelta(days=30)
        
    return Subscription(
        id=uuid.uuid4(),
        user=user.to_ref(),
        subscription_type=subscription_type,
        status=status,
        start_date=start_date,
        end_date=end_date,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )