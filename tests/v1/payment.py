import pytest
from httpx import AsyncClient
from unittest import mock
import uuid
from typing import Dict
from datetime import datetime, timedelta

from app.core.config import settings
from app.models.user import User
from app.core.security import create_access_token
from tests.utils.mock_data import create_mock_user # for specific payment states

@pytest.mark.asyncio
async def test_payment_endpoints_no_auth(client: AsyncClient):
    endpoints_to_test = [
        ("POST", f"{settings.API_V1_STR}/payments/stripe/create-checkout-session", {"payment_type": "one_time"}),
        ("GET", f"{settings.API_V1_STR}/payments/stripe/verify-payment?session_id=cs_test123", None),
        ("POST", f"{settings.API_V1_STR}/payments/usdt/initiate-payment", {"payment_type": "one_time"}),
        ("POST", f"{settings.API_V1_STR}/payments/usdt/confirm-payment?payment_attempt_id={uuid.uuid4()}&transaction_hash=0xtxhash", None),
        ("GET", f"{settings.API_V1_STR}/payments/status", None),
    ]
    for method, url, json_data in endpoints_to_test:
        if method == "POST":
            response = await client.post(url, json=json_data)
        else: # GET
            response = await client.get(url)
        assert response.status_code == 401, f"Failed for {method} {url}"
        assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_create_stripe_checkout_session_one_time(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], mock_stripe, test_user: User
):
    settings.STRIPE_SECRET_KEY = "sk_test_mock" # Ensure configured for this test
    settings.STRIPE_PUBLISHABLE_KEY = "pk_test_mock"
    
    mock_stripe["create"].return_value = mock.Mock(
        id="cs_test_onetimesession",
        url="https://checkout.stripe.com/pay/cs_test_onetimesession",
        metadata={"user_id": str(test_user.id), "payment_type": "one_time"}
    )

    response = await client.post(
        f"{settings.API_V1_STR}/payments/stripe/create-checkout-session",
        headers=auth_headers_for_user,
        json={"payment_type": "one_time"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "cs_test_onetimesession"
    assert data["url"] is not None
    mock_stripe["create"].assert_called_once()
    call_args = mock_stripe["create"].call_args[1] # kwargs
    assert call_args["mode"] == "payment"
    assert call_args["line_items"][0]["price_data"]["unit_amount"] == settings.ONE_TIME_PAYMENT_AMOUNT_USD
    assert call_args["metadata"]["payment_type"] == "one_time"
    settings.STRIPE_SECRET_KEY = None # Reset for other tests
    settings.STRIPE_PUBLISHABLE_KEY = None

@pytest.mark.asyncio
async def test_create_stripe_checkout_session_monthly(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], mock_stripe, test_user: User
):
    settings.STRIPE_SECRET_KEY = "sk_test_mock_monthly"
    settings.STRIPE_PUBLISHABLE_KEY = "pk_test_mock_monthly"
    mock_stripe["create"].return_value = mock.Mock(
        id="cs_test_monthlysession",
        url="https://checkout.stripe.com/pay/cs_test_monthlysession",
        metadata={"user_id": str(test_user.id), "payment_type": "monthly"}
    )

    response = await client.post(
        f"{settings.API_V1_STR}/payments/stripe/create-checkout-session",
        headers=auth_headers_for_user,
        json={"payment_type": "monthly"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "cs_test_monthlysession"
    mock_stripe["create"].assert_called_once()
    call_args = mock_stripe["create"].call_args[1]
    assert call_args["mode"] == "subscription"
    assert call_args["line_items"][0]["price_data"]["unit_amount"] == settings.MONTHLY_SUBSCRIPTION_AMOUNT_USD
    assert call_args["metadata"]["payment_type"] == "monthly"
    settings.STRIPE_SECRET_KEY = None
    settings.STRIPE_PUBLISHABLE_KEY = None

@pytest.mark.asyncio
async def test_verify_stripe_payment_success_one_time(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], mock_stripe, test_user: User, mock_user_db, mock_subscription_db
):
    settings.STRIPE_SECRET_KEY = "sk_test_mock_verify"
    session_id = "cs_test_paid_onetimesession"
    mock_stripe["retrieve"].return_value = mock.Mock(
        id=session_id,
        payment_status="paid",
        mode="payment", # One-time payment
        status="complete", # For payment mode, payment_status is key
        amount_total=settings.ONE_TIME_PAYMENT_AMOUNT_USD,
        currency="usd",
        payment_intent="pi_test123",
        metadata={"user_id": str(test_user.id), "payment_type": "one_time"}
    )

    response = await client.get(
        f"{settings.API_V1_STR}/payments/stripe/verify-payment?session_id={session_id}",
        headers=auth_headers_for_user,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["subscription_type"] == "one_time"
    assert data["is_active_subscriber"] is True
    
    # Verify user in mock_user_db is updated
    updated_user = mock_user_db.get(test_user.id)
    assert updated_user is not None
    assert updated_user.subscription_type == "one_time"
    
    # Verify subscription created in mock_subscription_db
    user_sub = None
    for sub in mock_subscription_db.values():
        if sub.user.id == test_user.id:
            user_sub = sub
            break
    assert user_sub is not None
    assert user_sub.subscription_type == "one_time"
    assert user_sub.status == "active"

    settings.STRIPE_SECRET_KEY = None

@pytest.mark.asyncio
async def test_verify_stripe_payment_success_monthly_subscription(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], mock_stripe, test_user: User, mock_user_db, mock_subscription_db
):
    settings.STRIPE_SECRET_KEY = "sk_test_mock_verify_monthly"
    session_id = "cs_test_paid_monthlysession"
    stripe_sub_id = "sub_mockstripe123"
    mock_stripe["retrieve"].return_value = mock.Mock(
        id=session_id,
        payment_status="paid", # For subscriptions, status "complete" might be more relevant
        mode="subscription",
        status="complete", # Indicates checkout session for subscription is complete
        subscription=stripe_sub_id, # Stripe subscription ID
        amount_total=settings.MONTHLY_SUBSCRIPTION_AMOUNT_USD, # Might be null if only setting up sub
        currency="usd",
        metadata={"user_id": str(test_user.id), "payment_type": "monthly"}
    )

    response = await client.get(
        f"{settings.API_V1_STR}/payments/stripe/verify-payment?session_id={session_id}",
        headers=auth_headers_for_user,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["subscription_type"] == "monthly"
    assert data["is_active_subscriber"] is True
    assert data["requests_remaining"] == settings.MONTHLY_REQUEST_LIMIT # Fresh subscription
    
    updated_user = mock_user_db.get(test_user.id)
    assert updated_user is not None
    assert updated_user.subscription_type == "monthly"
    assert updated_user.monthly_requests_used == 0 # Should be reset
    
    user_sub = None
    for sub in mock_subscription_db.values():
        if sub.user.id == test_user.id:
            user_sub = sub
            break
    assert user_sub is not None
    assert user_sub.subscription_type == "monthly"
    assert user_sub.status == "active"
    assert user_sub.payment_processor_subscription_id == stripe_sub_id
    assert user_sub.end_date is not None
    assert user_sub.end_date > datetime.utcnow()

    settings.STRIPE_SECRET_KEY = None


@pytest.mark.asyncio
async def test_verify_stripe_payment_pending(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], mock_stripe, test_user: User
):
    settings.STRIPE_SECRET_KEY = "sk_test_mock_verify_pending"
    session_id = "cs_test_pending_session"
    mock_stripe["retrieve"].return_value = mock.Mock(
        id=session_id,
        status="open", # Payment is still pending
        payment_status=None, # Or some other non-paid status
        mode="payment",
        metadata={"user_id": str(test_user.id), "payment_type": "one_time"}
    )
    response = await client.get(
        f"{settings.API_V1_STR}/payments/stripe/verify-payment?session_id={session_id}",
        headers=auth_headers_for_user,
    )
    assert response.status_code == 402 # PaymentRequiredError
    data = response.json()
    assert data["detail"] == "Payment is still pending completion."
    assert data["error_code"] == "STRIPE_PAYMENT_PENDING"
    settings.STRIPE_SECRET_KEY = None

@pytest.mark.asyncio
async def test_initiate_usdt_payment_one_time(client: AsyncClient, auth_headers_for_user: Dict[str, str], test_user: User, mock_payment_attempt_db):
    settings.USDT_ETH_WALLET_ADDRESS = "0xMockWalletAddress"
    response = await client.post(
        f"{settings.API_V1_STR}/payments/usdt/initiate-payment",
        headers=auth_headers_for_user,
        json={"payment_type": "one_time"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["wallet_address"] == settings.USDT_ETH_WALLET_ADDRESS
    assert data["expected_amount_usd"] == float(settings.ONE_TIME_PAYMENT_AMOUNT_USD / 100)
    assert data["payment_type"] == "one_time"
    assert "payment_attempt_id" in data
    
    # Check mock_payment_attempt_db
    payment_attempt = mock_payment_attempt_db.get(uuid.UUID(data["payment_attempt_id"]))
    assert payment_attempt is not None
    assert payment_attempt.user.id == test_user.id # Beanie's Link.id
    assert payment_attempt.status == "pending"
    assert payment_attempt.payment_method == "usdt"
    
    settings.USDT_ETH_WALLET_ADDRESS = None


@pytest.mark.asyncio
async def test_confirm_usdt_payment_success(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], test_user: User, mock_user_db, mock_payment_attempt_db, mock_subscription_db
):
    settings.USDT_ETH_WALLET_ADDRESS = "0xMockWalletAddress" # Needed if service checks it
    
    # First, initiate a payment to get a payment_attempt_id
    init_response = await client.post(
        f"{settings.API_V1_STR}/payments/usdt/initiate-payment",
        headers=auth_headers_for_user, json={"payment_type": "monthly"}
    )
    assert init_response.status_code == 200
    payment_attempt_id = init_response.json()["payment_attempt_id"]
    tx_hash = f"0x{uuid.uuid4().hex}" # Mock transaction hash

    # Now confirm it (mocking blockchain verification as successful in service)
    response = await client.post(
        f"{settings.API_V1_STR}/payments/usdt/confirm-payment?payment_attempt_id={payment_attempt_id}&transaction_hash={tx_hash}",
        headers=auth_headers_for_user,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["subscription_type"] == "monthly"
    assert data["is_active_subscriber"] is True

    # Check mock_payment_attempt_db
    confirmed_attempt = mock_payment_attempt_db.get(uuid.UUID(payment_attempt_id))
    assert confirmed_attempt is not None
    assert confirmed_attempt.status == "succeeded"
    assert confirmed_attempt.transaction_id == tx_hash

    # Check user and subscription in mock_dbs
    updated_user = mock_user_db.get(test_user.id)
    assert updated_user.subscription_type == "monthly"
    
    user_sub = None
    for sub in mock_subscription_db.values():
        if sub.user.id == test_user.id:
            user_sub = sub
            break
    assert user_sub is not None
    assert user_sub.subscription_type == "monthly"
    assert user_sub.status == "active"

    settings.USDT_ETH_WALLET_ADDRESS = None


@pytest.mark.asyncio
async def test_get_payment_status_free_user_no_requests(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], test_user: User
):
    # test_user by default has 0 free_requests_used
    response = await client.get(f"{settings.API_V1_STR}/payments/status", headers=auth_headers_for_user)
    assert response.status_code == 200
    data = response.json()
    assert data["subscription_type"] == "none" # Initial state
    assert data["is_active_subscriber"] is False
    assert data["requests_remaining"] == settings.FREE_REQUEST_LIMIT


@pytest.mark.asyncio
async def test_get_payment_status_free_user_limit_used(
    client: AsyncClient, mock_user_db, test_user: User
):
    # Modify test_user in mock_user_db to have used all free requests
    test_user.free_requests_used = settings.FREE_REQUEST_LIMIT
    test_user.subscription_type = "none" # Ensure it starts at none to trigger 'free_tier_used'
    mock_user_db[test_user.id] = test_user

    # Need to re-generate token if test_user was modified after auth_headers_for_user was created
    # For simplicity, assume test_user is fetched fresh by dependency for status check
    temp_auth_headers = {"Authorization": f"Bearer {create_access_token(subject=test_user.id)}"}

    response = await client.get(f"{settings.API_V1_STR}/payments/status", headers=temp_auth_headers)
    assert response.status_code == 200
    data = response.json()
    
    # Check user in DB has been updated
    updated_user_in_db = mock_user_db.get(test_user.id)
    assert updated_user_in_db.subscription_type == "free_tier_used"
    
    assert data["subscription_type"] == "free_tier_used" # Updated by the service
    assert data["is_active_subscriber"] is False
    assert data["requests_remaining"] == 0
    assert "User has used all free requests. Please subscribe." in data["message"]
    

@pytest.mark.asyncio
async def test_get_payment_status_one_time_subscriber(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], test_user: User, mock_user_db
):
    test_user.subscription_type = "one_time"
    mock_user_db[test_user.id] = test_user # Update mock_user_db directly

    response = await client.get(f"{settings.API_V1_STR}/payments/status", headers=auth_headers_for_user)
    assert response.status_code == 200
    data = response.json()
    assert data["subscription_type"] == "one_time"
    assert data["is_active_subscriber"] is True
    assert data["requests_remaining"] is None # Unlimited

@pytest.mark.asyncio
async def test_get_payment_status_monthly_subscriber_active(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], test_user: User, mock_user_db
):
    test_user.subscription_type = "monthly"
    test_user.subscription_end_date = datetime.utcnow() + timedelta(days=15)
    test_user.monthly_requests_used = 5
    mock_user_db[test_user.id] = test_user

    response = await client.get(f"{settings.API_V1_STR}/payments/status", headers=auth_headers_for_user)
    assert response.status_code == 200
    data = response.json()
    assert data["subscription_type"] == "monthly"
    assert data["is_active_subscriber"] is True
    assert data["requests_remaining"] == settings.MONTHLY_REQUEST_LIMIT - 5
    assert data["subscription_end_date"] is not None

@pytest.mark.asyncio
async def test_get_payment_status_monthly_subscriber_limit_reached(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], test_user: User, mock_user_db
):
    test_user.subscription_type = "monthly"
    test_user.subscription_end_date = datetime.utcnow() + timedelta(days=15)
    test_user.monthly_requests_used = settings.MONTHLY_REQUEST_LIMIT
    mock_user_db[test_user.id] = test_user

    response = await client.get(f"{settings.API_V1_STR}/payments/status", headers=auth_headers_for_user)
    assert response.status_code == 200
    data = response.json()
    assert data["subscription_type"] == "monthly"
    assert data["is_active_subscriber"] is True
    assert data["requests_remaining"] == 0

@pytest.mark.asyncio
async def test_get_payment_status_monthly_subscriber_expired(
    client: AsyncClient, auth_headers_for_user: Dict[str, str], test_user: User, mock_user_db
):
    test_user.subscription_type = "monthly"
    test_user.subscription_end_date = datetime.utcnow() - timedelta(days=1) # Expired
    mock_user_db[test_user.id] = test_user

    response = await client.get(f"{settings.API_V1_STR}/payments/status", headers=auth_headers_for_user)
    assert response.status_code == 200
    data = response.json()
    assert data["subscription_type"] == "monthly" # Service doesn't change it here, just reports
    assert data["is_active_subscriber"] is False
    assert "User's monthly subscription has expired." in data["message"]