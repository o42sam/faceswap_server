import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')) # Adjusted to point to project root from tests/app
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pytest
import pytest_asyncio
import asyncio # Added for the session-scoped event_loop
from httpx import AsyncClient
from typing import AsyncGenerator, Generator, Dict, Any
from unittest import mock
import uuid
from datetime import datetime, timedelta, timezone

from app.main import app # app must be imported after settings are potentially patched or loaded
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, get_password_hash
from app.models.user import User
# from app.db.mongodb_utils import connect_to_mongo, close_mongo_connection # Not directly used if mocked in lifespan
from tests.utils.mock_data import create_mock_user

# Override settings for testing if necessary
# CRITICAL: Ensure DATABASE_NAME is set for tests
settings.DATABASE_URL = "mongodb://localhost:27017" # Use a test DB or a mock URL
settings.DATABASE_NAME = "faceswap_saas_test_db"   # CRITICAL FIX for InvalidName error
settings.DEBUG = False # To ensure production-like error responses
settings.SECRET_KEY = "test_secret_key_for_jwt_please_change_in_prod_and_real_tests" # Ensure a secret key for tests
settings.GOOGLE_CLIENT_ID = "test_google_client_id" # Ensure these are set if Google OAuth tests run
settings.GOOGLE_CLIENT_SECRET = "test_google_client_secret"
settings.GOOGLE_REDIRECT_URI = "http://testserver/api/v1/auth/google/callback"


@pytest.fixture(scope="session")
def event_loop():
    """
    Create an instance of the default event loop for the entire session.
    pytest-asyncio uses this to run session-scoped async fixtures.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def app_lifespan_manager(): # Removed event_loop from signature
    # This fixture will manage the app's lifespan for the entire test session.
    # We mock connect_to_mongo and close_mongo_connection where they are called by the lifespan manager (app.main)
    
    # Patching where connect_to_mongo and close_mongo_connection are looked up by app.main.lifespan
    with mock.patch("app.main.connect_to_mongo", new_callable=mock.AsyncMock) as mock_connect, \
         mock.patch("app.main.close_mongo_connection", new_callable=mock.AsyncMock) as mock_close:
        # Simulate lifespan startup
        async with app.router.lifespan_context(app):
            yield # Tests run here
        # Lifespan shutdown is implicitly handled by context exit
        mock_connect.assert_called_once() # Ensure our lifespan startup mock was called
        mock_close.assert_called_once() # Ensure lifespan shutdown mock was called


@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(app=app, base_url="http://testserver") as c:
        yield c

@pytest.fixture(scope="function")
def mock_user_db() -> Dict[uuid.UUID, User]:
    return {}

@pytest.fixture(scope="function")
def mock_google_id_db() -> Dict[str, User]:
    return {}
    
@pytest.fixture(scope="function")
def mock_payment_attempt_db() -> Dict[uuid.UUID, Any]: # Store mock PaymentAttempt
    return {}

@pytest.fixture(scope="function")
def mock_subscription_db() -> Dict[uuid.UUID, Any]: # Store mock Subscription
    return {}


@pytest_asyncio.fixture(scope="function")
async def test_user(mock_user_db: Dict[uuid.UUID, User]) -> User:
    user = create_mock_user(email="test@example.com", password="password", user_id=uuid.uuid4())
    mock_user_db[user.id] = user
    return user

@pytest_asyncio.fixture(scope="function")
async def test_user_google(mock_user_db: Dict[uuid.UUID, User], mock_google_id_db: Dict[str, User]) -> User:
    user = create_mock_user(
        email="googleuser@example.com",
        password=None, # Google users might not have a password initially
        google_id="test_google_id_123",
        user_id=uuid.uuid4()
    )
    mock_user_db[user.id] = user
    mock_google_id_db[user.google_id] = user
    return user
    
@pytest_asyncio.fixture(scope="function")
async def other_user(mock_user_db: Dict[uuid.UUID, User]) -> User:
    user = create_mock_user(email="other@example.com", password="password", user_id=uuid.uuid4())
    mock_user_db[user.id] = user
    return user


@pytest.fixture(scope="function")
def auth_headers_for_user(test_user: User) -> Dict[str, str]:
    access_token = create_access_token(subject=test_user.id)
    return {"Authorization": f"Bearer {access_token}"}

@pytest.fixture(scope="function")
def auth_headers_for_google_user(test_user_google: User) -> Dict[str, str]:
    access_token = create_access_token(subject=test_user_google.id)
    return {"Authorization": f"Bearer {access_token}"}


# --- Mock CRUD operations ---
@pytest_asyncio.fixture(scope="function", autouse=True)
async def mock_crud_user_operations(mock_user_db, mock_google_id_db):
    async def mock_get_user_by_email(email: str):
        for user_instance in mock_user_db.values():
            if user_instance.email == email:
                return user_instance
        return None

    async def mock_get_user_by_id(user_id: uuid.UUID):
        # Ensure user_id is uuid.UUID for dictionary lookup
        if isinstance(user_id, str):
            try:
                user_id = uuid.UUID(user_id)
            except ValueError:
                return None
        return mock_user_db.get(user_id)


    async def mock_get_user_by_google_id(google_id: str):
        return mock_google_id_db.get(google_id)

    async def mock_create_user(user_in):
        new_id = uuid.uuid4()
        user_data = {
            "id": new_id,
            "email": user_in.email.lower(),
            "hashed_password": get_password_hash(user_in.password),
            "full_name": user_in.full_name if hasattr(user_in, 'full_name') else None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "is_active": True,
            "is_superuser": False,
            "subscription_type": "none",
            "free_requests_used": 0,
            "monthly_requests_used": 0
        }
        user_instance = User(**user_data)
        mock_user_db[new_id] = user_instance
        return user_instance

    async def mock_create_user_google(user_in):
        new_id = uuid.uuid4()
        user_data = {
            "id": new_id,
            "email": user_in.email.lower(),
            "google_id": user_in.google_id,
            "full_name": user_in.full_name if hasattr(user_in, 'full_name') else None,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "subscription_type": "none",
            "free_requests_used": 0,
            "monthly_requests_used": 0
        }
        user_instance = User(**user_data)
        mock_user_db[new_id] = user_instance
        if user_in.google_id: # Ensure google_id exists before adding to this dict
            mock_google_id_db[user_in.google_id] = user_instance
        return user_instance
    
    async def mock_save_user(user_instance: User): # Simulates user.save()
        if user_instance.id in mock_user_db:
            user_instance.updated_at = datetime.now(timezone.utc)
            mock_user_db[user_instance.id] = user_instance
        if user_instance.google_id and user_instance.google_id in mock_google_id_db:
             mock_google_id_db[user_instance.google_id] = user_instance
        return user_instance 
    
    async def mock_increment_user_request_count(user_instance: User, is_free_request: bool):
        if is_free_request:
            user_instance.free_requests_used += 1
        else:
            user_instance.monthly_requests_used += 1
        user_instance.last_request_date = datetime.now(timezone.utc)
        await mock_save_user(user_instance)

    async def mock_reset_monthly_user_request_count(user_instance: User):
        user_instance.monthly_requests_used = 0
        await mock_save_user(user_instance)

    # Patch User.save as an instance method
    # For Beanie, model instance methods like save() are often better mocked
    # by patching the method on the class itself if all instances should use the mock.
    # Or, if only specific instances, more targeted mocking is needed.
    # Here, we use a callable that will be assigned to User.save,
    # implying it replaces the instance method behavior.
    # This mock_save_user will be called with 'self' as the first argument (the user_instance).
    async def actual_user_save_mock(self_user_instance: User): # 'self' is the User instance
        return await mock_save_user(self_user_instance)

    with mock.patch("app.repositories.user.get_user_by_email", side_effect=mock_get_user_by_email), \
         mock.patch("app.repositories.user.get_user_by_id", side_effect=mock_get_user_by_id), \
         mock.patch("app.repositories.user.get_user_by_google_id", side_effect=mock_get_user_by_google_id), \
         mock.patch("app.repositories.user.create_user", side_effect=mock_create_user), \
         mock.patch("app.repositories.user.create_user_google", side_effect=mock_create_user_google), \
         mock.patch("app.models.user.User.save", new=actual_user_save_mock), \
         mock.patch("app.repositories.user.increment_user_request_count", side_effect=mock_increment_user_request_count), \
         mock.patch("app.repositories.user.reset_monthly_user_request_count", side_effect=mock_reset_monthly_user_request_count):
        yield

@pytest_asyncio.fixture(scope="function", autouse=True)
async def mock_crud_payment_operations(mock_user_db, mock_payment_attempt_db, mock_subscription_db):
    from app.models.payment import PaymentAttempt, Subscription 
    from app.models.user import User as UserModel # Alias to avoid confusion
    from beanie.odm.fields import Link # Import Link for type checking

    async def mock_create_payment_attempt(user: UserModel, amount, currency, payment_method, status="pending", **kwargs):
        attempt_id = uuid.uuid4()
        
        # Simulate Beanie's Link creation
        user_ref = Link(document=user, document_type=UserModel)

        attempt = PaymentAttempt(
            id=attempt_id,
            user=user_ref, 
            amount=amount,
            currency=currency,
            payment_method=payment_method,
            status=status,
            metadata=kwargs.get("metadata", {}),
            transaction_id=kwargs.get("transaction_id"),
            payment_processor=kwargs.get("payment_processor"),
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
        )
        mock_payment_attempt_db[attempt_id] = attempt
        return attempt

    async def mock_get_payment_attempt(payment_attempt_id: uuid.UUID):
        return mock_payment_attempt_db.get(payment_attempt_id)

    async def mock_update_payment_attempt_status(payment_attempt, status, **kwargs):
        payment_attempt.status = status
        if "transaction_id" in kwargs:
            payment_attempt.transaction_id = kwargs["transaction_id"]
        if "metadata" in kwargs:
            payment_attempt.metadata = {**(payment_attempt.metadata or {}), **kwargs["metadata"]}
        payment_attempt.updated_at = datetime.now(timezone.utc)
        mock_payment_attempt_db[payment_attempt.id] = payment_attempt 
        return payment_attempt

    async def mock_create_or_update_subscription(user: UserModel, subscription_type, **kwargs):
        sub_id = uuid.uuid4()
        user_ref = Link(document=user, document_type=UserModel)

        existing_sub_id = None
        # Check if user object itself has subscription_id from mock_user_db
        # or iterate mock_subscription_db
        for sub_uuid_iter, sub_instance_iter in mock_subscription_db.items():
            # Need to fetch the user from the Link to compare IDs if sub_instance_iter.user is a Link
            # For simplicity, if user.id is directly comparable or we assume it's fetched.
            # Let's assume the Link's document is already the user object for mock comparison
            if isinstance(sub_instance_iter.user, Link) and sub_instance_iter.user.ref.id == user.id:
                 existing_sub_id = sub_uuid_iter
                 sub_id = existing_sub_id
                 break
            elif hasattr(sub_instance_iter.user, 'id') and sub_instance_iter.user.id == user.id: # If it's already a User object
                 existing_sub_id = sub_uuid_iter
                 sub_id = existing_sub_id
                 break


        start_date = kwargs.get("start_date", datetime.now(timezone.utc))
        end_date = kwargs.get("end_date")
        if subscription_type == "monthly" and not end_date:
            end_date = start_date + timedelta(days=settings.MONTHLY_SUBSCRIPTION_DURATION_DAYS if hasattr(settings, 'MONTHLY_SUBSCRIPTION_DURATION_DAYS') else 30)


        sub = Subscription(
            id=sub_id,
            user=user_ref,
            subscription_type=subscription_type,
            status=kwargs.get("status", "active"),
            start_date=start_date,
            end_date=end_date,
            payment_processor_subscription_id=kwargs.get("payment_processor_subscription_id"),
            last_payment_date=start_date, 
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
        )
        mock_subscription_db[sub_id] = sub
        
        # Update the user object in mock_user_db as well
        user_in_db = mock_user_db.get(user.id)
        if user_in_db:
            user_in_db.subscription_type = subscription_type
            user_in_db.subscription_id = str(sub_id) # Store as string
            user_in_db.subscription_start_date = start_date
            user_in_db.subscription_end_date = end_date
            if subscription_type == "monthly":
                user_in_db.monthly_requests_used = 0
            mock_user_db[user.id] = user_in_db # Save changes back to the mock_user_db
        return sub

    async def mock_get_user_subscription(user: UserModel):
        for sub_instance in mock_subscription_db.values():
            if isinstance(sub_instance.user, Link) and sub_instance.user.ref.id == user.id:
                return sub_instance
            elif hasattr(sub_instance.user, 'id') and sub_instance.user.id == user.id:
                return sub_instance
        return None
        
    with mock.patch("app.repositories.payment.create_payment_attempt", side_effect=mock_create_payment_attempt), \
         mock.patch("app.repositories.payment.get_payment_attempt", side_effect=mock_get_payment_attempt), \
         mock.patch("app.repositories.payment.update_payment_attempt_status", side_effect=mock_update_payment_attempt_status), \
         mock.patch("app.repositories.payment.create_or_update_subscription", side_effect=mock_create_or_update_subscription), \
         mock.patch("app.repositories.payment.get_user_subscription", side_effect=mock_get_user_subscription):
        yield

# Mock external services (Stripe, Google OAuth)
@pytest_asyncio.fixture(scope="function")
async def mock_stripe():
    with mock.patch("stripe.checkout.Session.create", new_callable=mock.AsyncMock) as mock_create, \
         mock.patch("stripe.checkout.Session.retrieve", new_callable=mock.AsyncMock) as mock_retrieve:
        yield {
            "create": mock_create,
            "retrieve": mock_retrieve
        }

@pytest_asyncio.fixture(scope="function")
async def mock_google_oauth_client():
    # This fixture mocks the `google_flow` object from `app.services.auth`
    # and the `id_token.verify_oauth2_token` function.
    
    mock_flow_instance = mock.AsyncMock() # Use AsyncMock for flow if its methods are async
    
    # Mock authorization_url method
    mock_flow_instance.authorization_url = mock.Mock(return_value=("https://mock.google.com/auth?client_id=test", "mock_state"))
    
    # Mock fetch_token method
    # This method in google-auth-oauthlib typically doesn't return anything directly for the 'code' flow;
    # it populates the flow instance's credentials.
    mock_flow_instance.fetch_token = mock.Mock() # Not async if it's synchronous
    
    # Mock credentials attribute that fetch_token would populate
    mock_credentials = mock.Mock()
    mock_credentials.id_token = "mock_google_id_token_string"
    mock_flow_instance.credentials = mock_credentials

    # We also need to mock `google.oauth2.id_token.verify_oauth2_token`
    # as it's called directly in the auth service.
    with mock.patch("app.services.auth.google_flow", mock_flow_instance), \
         mock.patch("app.services.auth.id_token.verify_oauth2_token") as mock_verify_id_token:
        
        yield {
            "flow": mock_flow_instance,
            "verify_id_token": mock_verify_id_token # This is the mock for id_token.verify_oauth2_token
        }