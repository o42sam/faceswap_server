import pytest
import pytest_asyncio
from httpx import AsyncClient
from typing import AsyncGenerator, Generator, Dict, Any
from unittest import mock
import uuid
from datetime import datetime, timedelta, timezone

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.models.user import User
from app.db.mongodb_utils import connect_to_mongo, close_mongo_connection
from tests.utils.mock_data import create_mock_user

# Override settings for testing if necessary
# settings.DATABASE_URL = "mongodb://localhost:27017" # Use a test DB if not mocking everything
# settings.DATABASE_NAME = "faceswap_saas_test_db"
settings.DEBUG = False # To ensure production-like error responses


@pytest_asyncio.fixture(scope="session", autouse=True)
async def app_lifespan_manager():
    # This fixture will manage the app's lifespan for the entire test session.
    # We mock connect_to_mongo and close_mongo_connection if we don't want to hit a real DB.
    # For endpoint tests where CRUD is mocked, this might not be strictly necessary for DB part.
    # However, if other lifespan events exist, it's good practice.
    
    # If you were using a real test DB:
    # await connect_to_mongo() # Connect to test DB
    # yield
    # # Clean up test DB
    # client = AsyncIOMotorClient(str(settings.DATABASE_URL))
    # await client.drop_database(settings.DATABASE_NAME)
    # await close_mongo_connection()

    # For fully mocked DB tests:
    with mock.patch("app.db.mongodb_utils.connect_to_mongo", new_callable=mock.AsyncMock) as mock_connect, \
         mock.patch("app.db.mongodb_utils.close_mongo_connection", new_callable=mock.AsyncMock) as mock_close:
        # Simulate lifespan startup
        async with app.router.lifespan_context(app):
            yield # Tests run here
        # Lifespan shutdown is implicitly handled by context exit
        mock_connect.assert_called_once() # Ensure our lifespan startup mock was called
        # mock_close will be asserted by lifespan_context exit if it's part of shutdown


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
# These mocks will intercept calls to the CRUD layer.
# You can expand these to return specific data or raise exceptions as needed by tests.

@pytest_asyncio.fixture(scope="function", autouse=True)
async def mock_crud_user_operations(mock_user_db, mock_google_id_db):
    async def mock_get_user_by_email(email: str):
        for user in mock_user_db.values():
            if user.email == email:
                return user
        return None

    async def mock_get_user_by_id(user_id: uuid.UUID):
        return mock_user_db.get(user_id)

    async def mock_get_user_by_google_id(google_id: str):
        return mock_google_id_db.get(google_id)

    async def mock_create_user(user_in):
        new_id = uuid.uuid4()
        user = User(
            id=new_id,
            email=user_in.email.lower(),
            hashed_password=get_password_hash(user_in.password),
            full_name=user_in.full_name,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        mock_user_db[new_id] = user
        return user

    async def mock_create_user_google(user_in):
        new_id = uuid.uuid4()
        user = User(
            id=new_id,
            email=user_in.email.lower(),
            google_id=user_in.google_id,
            full_name=user_in.full_name,
            is_active=True, # Assume active
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        mock_user_db[new_id] = user
        mock_google_id_db[user_in.google_id] = user
        return user
    
    async def mock_save_user(user_instance: User): # Simulates user.save()
        if user_instance.id in mock_user_db:
            mock_user_db[user_instance.id] = user_instance
            user_instance.updated_at = datetime.utcnow() # Mimic beanie behavior
        if user_instance.google_id and user_instance.google_id in mock_google_id_db:
            mock_google_id_db[user_instance.google_id] = user_instance
        return user_instance
    
    async def mock_increment_user_request_count(user: User, is_free_request: bool):
        if is_free_request:
            user.free_requests_used += 1
        else:
            user.monthly_requests_used += 1
        user.last_request_date = datetime.utcnow()
        await mock_save_user(user) # Save changes to mock_user_db

    async def mock_reset_monthly_user_request_count(user: User):
        user.monthly_requests_used = 0
        await mock_save_user(user)


    with mock.patch("app.crud.crud_user.get_user_by_email", side_effect=mock_get_user_by_email), \
         mock.patch("app.crud.crud_user.get_user_by_id", side_effect=mock_get_user_by_id), \
         mock.patch("app.crud.crud_user.get_user_by_google_id", side_effect=mock_get_user_by_google_id), \
         mock.patch("app.crud.crud_user.create_user", side_effect=mock_create_user), \
         mock.patch("app.crud.crud_user.create_user_google", side_effect=mock_create_user_google), \
         mock.patch("app.models.user.User.save", side_effect=mock_save_user), \
         mock.patch("app.crud.crud_user.increment_user_request_count", side_effect=mock_increment_user_request_count), \
         mock.patch("app.crud.crud_user.reset_monthly_user_request_count", side_effect=mock_reset_monthly_user_request_count):
        yield

@pytest_asyncio.fixture(scope="function", autouse=True)
async def mock_crud_payment_operations(mock_user_db, mock_payment_attempt_db, mock_subscription_db):
    from app.models.payment import PaymentAttempt, Subscription # Import here to avoid circularity if models use CRUD
    from app.models.user import User as UserModel # Ensure correct User type

    async def mock_create_payment_attempt(user: UserModel, amount, currency, payment_method, status="pending", **kwargs):
        attempt_id = uuid.uuid4()
        attempt = PaymentAttempt(
            id=attempt_id,
            user=user.to_ref(), # Assuming to_ref() works or mock it
            amount=amount,
            currency=currency,
            payment_method=payment_method,
            status=status,
            metadata=kwargs.get("metadata", {}),
            transaction_id=kwargs.get("transaction_id"),
            payment_processor=kwargs.get("payment_processor"),
            created_at=datetime.utcnow(), updated_at=datetime.utcnow()
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
        payment_attempt.updated_at = datetime.utcnow()
        mock_payment_attempt_db[payment_attempt.id] = payment_attempt # Ensure update
        return payment_attempt

    async def mock_create_or_update_subscription(user: UserModel, subscription_type, **kwargs):
        sub_id = uuid.uuid4() # Simplified: always create new for mock, or find existing based on user.id
        
        # Try to find existing for the user
        existing_sub_id = None
        for sub_uuid, sub_instance in mock_subscription_db.items():
            if sub_instance.user.id == user.id: # Beanie's Link might need .id for comparison in mock
                existing_sub_id = sub_uuid
                sub_id = existing_sub_id
                break
        
        start_date = kwargs.get("start_date", datetime.utcnow())
        end_date = kwargs.get("end_date")
        if subscription_type == "monthly" and not end_date:
            end_date = start_date + timedelta(days=30)

        sub = Subscription(
            id=sub_id,
            user=user.to_ref(),
            subscription_type=subscription_type,
            status=kwargs.get("status", "active"),
            start_date=start_date,
            end_date=end_date,
            payment_processor_subscription_id=kwargs.get("payment_processor_subscription_id"),
            last_payment_date=start_date, # Assume payment made at start_date
            created_at=datetime.utcnow(), updated_at=datetime.utcnow()
        )
        mock_subscription_db[sub_id] = sub
        
        # Update user model as well
        user_in_db = mock_user_db.get(user.id)
        if user_in_db:
            user_in_db.subscription_type = subscription_type
            user_in_db.subscription_id = str(sub_id)
            user_in_db.subscription_start_date = start_date
            user_in_db.subscription_end_date = end_date
            if subscription_type == "monthly":
                user_in_db.monthly_requests_used = 0
            mock_user_db[user.id] = user_in_db # Save updated user
        return sub

    async def mock_get_user_subscription(user: UserModel):
        for sub in mock_subscription_db.values():
            if sub.user.id == user.id: # Compare by ID
                return sub
        return None
        
    with mock.patch("app.crud.crud_payment.create_payment_attempt", side_effect=mock_create_payment_attempt), \
         mock.patch("app.crud.crud_payment.get_payment_attempt", side_effect=mock_get_payment_attempt), \
         mock.patch("app.crud.crud_payment.update_payment_attempt_status", side_effect=mock_update_payment_attempt_status), \
         mock.patch("app.crud.crud_payment.create_or_update_subscription", side_effect=mock_create_or_update_subscription), \
         mock.patch("app.crud.crud_payment.get_user_subscription", side_effect=mock_get_user_subscription):
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
    # Mock the client instance directly if it's stored in auth_service
    # Or mock the methods if called as class methods from GoogleOAuth2
    mock_client_instance = mock.AsyncMock()
    mock_client_instance.get_authorize_redirect = mock.AsyncMock(return_value="https://mock.google.com/auth?client_id=test")
    mock_client_instance.get_access_token = mock.AsyncMock() # To be configured per test
    mock_client_instance.get_id_email = mock.AsyncMock()    # To be configured per test

    with mock.patch("app.services.auth_service.google_oauth_client", mock_client_instance):
         yield mock_client_instance