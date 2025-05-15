import pytest
from httpx import AsyncClient
from unittest import mock
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.security import create_refresh_token, decode_token
from app.schemas.token_schemas import TokenPayload
from app.models.user import User # Import User model for type hinting
from tests.utils.mock_data import create_mock_user


@pytest.mark.asyncio
async def test_register_user_success(client: AsyncClient, mock_user_db):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/register",
        json={"email": "newuser@example.com", "password": "newpassword123", "full_name": "New User"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["full_name"] == "New User"
    assert "id" in data
    
    # Check if user was "created" in mock_user_db by the mocked CRUD
    created_user = None
    for user in mock_user_db.values():
        if user.email == "newuser@example.com":
            created_user = user
            break
    assert created_user is not None
    assert created_user.full_name == "New User"


@pytest.mark.asyncio
async def test_register_user_existing_email(client: AsyncClient, test_user: User, mock_user_db):
    # test_user fixture already populates mock_user_db via mock_crud_user_operations
    response = await client.post(
        f"{settings.API_V1_STR}/auth/register",
        json={"email": test_user.email, "password": "newpassword123", "full_name": "Another User"},
    )
    assert response.status_code == 409 # DuplicateResourceError
    data = response.json()
    assert data["detail"] == "User with this email already exists"
    assert data["error_code"] == "EMAIL_EXISTS"

@pytest.mark.asyncio
async def test_register_user_invalid_data(client: AsyncClient):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/register",
        json={"email": "invalidemail", "password": "short", "full_name": "Test"},
    )
    assert response.status_code == 422 # RequestValidationError
    data = response.json()
    assert "detail" in data
    assert len(data["detail"]) > 0 # FastAPI returns a list of errors

@pytest.mark.asyncio
async def test_login_email_password_success(client: AsyncClient, test_user: User, mock_user_db):
    # Ensure test_user is in mock_user_db with a hashed password
    # This is handled by create_mock_user and mock_crud_user_operations
    response = await client.post(
        f"{settings.API_V1_STR}/auth/login/email",
        data={"username": test_user.email, "password": "password"}, # test_user's password
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"

@pytest.mark.asyncio
async def test_login_email_password_incorrect_password(client: AsyncClient, test_user: User):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/login/email",
        data={"username": test_user.email, "password": "wrongpassword"},
    )
    assert response.status_code == 401 # AuthError
    data = response.json()
    assert data["detail"] == "Incorrect email or password"
    assert data["error_code"] == "LOGIN_INVALID_CREDENTIALS"

@pytest.mark.asyncio
async def test_login_email_non_existent_user(client: AsyncClient):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/login/email",
        data={"username": "nosuchuser@example.com", "password": "password"},
    )
    assert response.status_code == 401 # AuthError (user not found by mock_get_user_by_email)
    data = response.json()
    # Detail message can vary based on whether user is found or password is wrong for security
    assert data["error_code"] == "LOGIN_INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient, mock_user_db):
    inactive_user = create_mock_user(email="inactive@example.com", password="password", is_active=False, user_id=uuid.uuid4())
    mock_user_db[inactive_user.id] = inactive_user

    response = await client.post(
        f"{settings.API_V1_STR}/auth/login/email",
        data={"username": inactive_user.email, "password": "password"},
    )
    assert response.status_code == 401 # AuthError from service layer
    data = response.json()
    assert data["detail"] == "Inactive user"
    assert data["error_code"] == "INACTIVE_USER"
    
@pytest.mark.asyncio
async def test_login_google_user_with_no_password_via_email_login(client: AsyncClient, test_user_google: User):
    # test_user_google is created without a password
    response = await client.post(
        f"{settings.API_V1_STR}/auth/login/email",
        data={"username": test_user_google.email, "password": "anypassword"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["detail"] == "Incorrect email or password (user may have registered with Google)"
    assert data["error_code"] == "LOGIN_INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_refresh_token_success(client: AsyncClient, test_user: User):
    refresh_token = create_refresh_token(subject=test_user.id)
    response = await client.post(
        f"{settings.API_V1_STR}/auth/token/refresh?refresh_token={refresh_token}"
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data # Assuming new refresh token is issued
    payload = decode_token(data["access_token"])
    assert payload.sub == test_user.id
    assert payload.type == "access"

@pytest.mark.asyncio
async def test_refresh_token_invalid_token(client: AsyncClient):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/token/refresh?refresh_token=invalidtokenstring"
    )
    assert response.status_code == 401 # AuthError from decode_token
    data = response.json()
    assert data["detail"] == "Could not validate credentials" # or specific to refresh token
    assert data["error_code"] == "INVALID_TOKEN" # or INVALID_REFRESH_TOKEN

@pytest.mark.asyncio
async def test_refresh_token_using_access_token(client: AsyncClient, test_user: User):
    access_token = create_access_token(subject=test_user.id)
    response = await client.post(
        f"{settings.API_V1_STR}/auth/token/refresh?refresh_token={access_token}"
    )
    assert response.status_code == 401 # AuthError from service check
    data = response.json()
    assert data["detail"] == "Invalid refresh token"
    assert data["error_code"] == "INVALID_REFRESH_TOKEN_TYPE"

@pytest.mark.asyncio
async def test_google_login_authorize(client: AsyncClient, mock_google_oauth_client):
    # Ensure Google OAuth settings are present for this test if service checks them
    original_client_id = settings.GOOGLE_CLIENT_ID
    settings.GOOGLE_CLIENT_ID = "test_client_id_for_google_auth_url" # Ensure it's set
    settings.GOOGLE_CLIENT_SECRET = "test_client_secret_for_google_auth_url"
    settings.GOOGLE_REDIRECT_URI = "http://testserver/api/v1/auth/google/callback"


    response = await client.get(f"{settings.API_V1_STR}/auth/google/login")
    settings.GOOGLE_CLIENT_ID = original_client_id # Reset

    assert response.status_code == 200
    data = response.json()
    assert "authorize_url" in data
    assert data["authorize_url"] == "https://mock.google.com/auth?client_id=test" # From mock_google_oauth_client
    mock_google_oauth_client.get_authorize_redirect.assert_called_once()

@pytest.mark.asyncio
async def test_google_login_authorize_not_configured(client: AsyncClient):
    original_client_id = settings.GOOGLE_CLIENT_ID
    settings.GOOGLE_CLIENT_ID = None # Simulate not configured
    
    # Temporarily replace the google_oauth_client in auth_service for this test's scope
    with mock.patch("app.services.auth_service.google_oauth_client", None):
        response = await client.get(f"{settings.API_V1_STR}/auth/google/login")
    
    settings.GOOGLE_CLIENT_ID = original_client_id # Reset
    
    assert response.status_code == 500 # AppLogicError
    data = response.json()
    assert data["detail"] == "Google OAuth not configured"
    assert data["error_code"] == "GOOGLE_OAUTH_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_google_callback_new_user(client: AsyncClient, mock_google_oauth_client, mock_user_db, mock_google_id_db):
    settings.GOOGLE_CLIENT_ID = "test_client_id_for_google_auth_url"
    settings.GOOGLE_CLIENT_SECRET = "test_client_secret_for_google_auth_url"
    settings.GOOGLE_REDIRECT_URI = "http://testserver/api/v1/auth/google/callback"
    
    mock_google_oauth_client.get_access_token.return_value = {"access_token": "mock_google_access_token"}
    mock_google_oauth_client.get_id_email.return_value = {
        "id": "new_google_user_123",
        "email": "newgoogle@example.com",
        "name": "New Google User"
    }

    response = await client.get(f"{settings.API_V1_STR}/auth/google/callback?code=test_auth_code")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    
    # Verify user was created in mock DBs
    created_user = None
    for user in mock_user_db.values():
        if user.email == "newgoogle@example.com":
            created_user = user
            break
    assert created_user is not None
    assert created_user.google_id == "new_google_user_123"
    assert created_user.full_name == "New Google User"
    assert mock_google_id_db.get("new_google_user_123") is not None

@pytest.mark.asyncio
async def test_google_callback_existing_user_by_google_id(client: AsyncClient, mock_google_oauth_client, test_user_google: User):
    settings.GOOGLE_CLIENT_ID = "test_client_id_for_google_auth_url"
    settings.GOOGLE_CLIENT_SECRET = "test_client_secret_for_google_auth_url"
    settings.GOOGLE_REDIRECT_URI = "http://testserver/api/v1/auth/google/callback"

    mock_google_oauth_client.get_access_token.return_value = {"access_token": "mock_google_access_token"}
    mock_google_oauth_client.get_id_email.return_value = {
        "id": test_user_google.google_id, # Existing Google ID
        "email": test_user_google.email,
        "name": test_user_google.full_name
    }

    response = await client.get(f"{settings.API_V1_STR}/auth/google/callback?code=test_auth_code")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    payload = decode_token(data["access_token"])
    assert payload.sub == test_user_google.id


@pytest.mark.asyncio
async def test_google_callback_link_to_existing_email_user(client: AsyncClient, mock_google_oauth_client, test_user: User, mock_user_db):
    # test_user exists, but no google_id initially
    assert test_user.google_id is None
    settings.GOOGLE_CLIENT_ID = "test_client_id_for_google_auth_url"
    settings.GOOGLE_CLIENT_SECRET = "test_client_secret_for_google_auth_url"
    settings.GOOGLE_REDIRECT_URI = "http://testserver/api/v1/auth/google/callback"


    mock_google_oauth_client.get_access_token.return_value = {"access_token": "mock_google_access_token"}
    mock_google_oauth_client.get_id_email.return_value = {
        "id": "google_id_for_linking",
        "email": test_user.email, # Existing email
        "name": test_user.full_name
    }

    response = await client.get(f"{settings.API_V1_STR}/auth/google/callback?code=test_auth_code")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    
    # Verify test_user in mock_user_db now has the google_id
    updated_user = mock_user_db.get(test_user.id)
    assert updated_user is not None
    assert updated_user.google_id == "google_id_for_linking"


@pytest.mark.asyncio
async def test_google_callback_invalid_code(client: AsyncClient, mock_google_oauth_client):
    settings.GOOGLE_CLIENT_ID = "test_client_id_for_google_auth_url"
    settings.GOOGLE_CLIENT_SECRET = "test_client_secret_for_google_auth_url"
    settings.GOOGLE_REDIRECT_URI = "http://testserver/api/v1/auth/google/callback"

    mock_google_oauth_client.get_access_token.side_effect = Exception("Google token error from mock")

    response = await client.get(f"{settings.API_V1_STR}/auth/google/callback?code=invalid_code")
    assert response.status_code == 401 # AuthError
    data = response.json()
    assert "Google token error from mock" in data["detail"]
    assert data["error_code"] == "GOOGLE_TOKEN_ERROR"


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, auth_headers_for_user: Dict[str, str]):
    response = await client.post(f"{settings.API_V1_STR}/auth/logout", headers=auth_headers_for_user)
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Successfully logged out (client should delete token)"