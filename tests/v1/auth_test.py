import pytest
from httpx import AsyncClient
from unittest import mock
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.security import create_refresh_token, decode_token, create_access_token # Added create_access_token
from app.schemas.token_schemas import TokenPayload
from app.models.user import User # Import User model for type hinting
from tests.utils.mock_data import create_mock_user
from typing import Dict


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
    
    created_user = None
    for user_obj in mock_user_db.values(): # Renamed user to user_obj to avoid conflict
        if user_obj.email == "newuser@example.com":
            created_user = user_obj
            break
    assert created_user is not None
    assert created_user.full_name == "New User"


@pytest.mark.asyncio
async def test_register_user_existing_email(client: AsyncClient, test_user: User, mock_user_db):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/register",
        json={"email": test_user.email, "password": "newpassword123", "full_name": "Another User"},
    )
    assert response.status_code == 409
    data = response.json()
    assert data["detail"] == "User with this email already exists"
    assert data["error_code"] == "EMAIL_EXISTS"

@pytest.mark.asyncio
async def test_register_user_invalid_data(client: AsyncClient):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/register",
        json={"email": "invalidemail", "password": "short", "full_name": "Test"},
    )
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
    assert len(data["detail"]) > 0

@pytest.mark.asyncio
async def test_login_email_password_success(client: AsyncClient, test_user: User, mock_user_db):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/login/email",
        data={"username": test_user.email, "password": "password"},
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
    assert response.status_code == 401
    data = response.json()
    assert data["detail"] == "Incorrect email or password"
    assert data["error_code"] == "LOGIN_INVALID_CREDENTIALS"

@pytest.mark.asyncio
async def test_login_email_non_existent_user(client: AsyncClient):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/login/email",
        data={"username": "nosuchuser@example.com", "password": "password"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error_code"] == "LOGIN_INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient, mock_user_db):
    inactive_user_id = uuid.uuid4()
    inactive_user = create_mock_user(email="inactive@example.com", password="password", is_active=False, user_id=inactive_user_id)
    mock_user_db[inactive_user.id] = inactive_user

    response = await client.post(
        f"{settings.API_V1_STR}/auth/login/email",
        data={"username": inactive_user.email, "password": "password"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["detail"] == "Inactive user"
    assert data["error_code"] == "INACTIVE_USER"
    
@pytest.mark.asyncio
async def test_login_google_user_with_no_password_via_email_login(client: AsyncClient, test_user_google: User):
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
    refresh_token = create_refresh_token(subject=str(test_user.id)) # Ensure subject is string for JWT
    response = await client.post(
        f"{settings.API_V1_STR}/auth/token/refresh?refresh_token={refresh_token}"
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    payload = decode_token(data["access_token"])
    assert payload.sub == test_user.id # decode_token returns payload.sub as UUID if original was UUID
    assert payload.type == "access"

@pytest.mark.asyncio
async def test_refresh_token_invalid_token(client: AsyncClient):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/token/refresh?refresh_token=invalidtokenstring"
    )
    assert response.status_code == 401
    data = response.json()
    assert data["detail"] == "Could not validate credentials"
    assert data["error_code"] == "INVALID_TOKEN"

@pytest.mark.asyncio
async def test_refresh_token_using_access_token(client: AsyncClient, test_user: User):
    access_token = create_access_token(subject=str(test_user.id)) # Ensure subject is string
    response = await client.post(
        f"{settings.API_V1_STR}/auth/token/refresh?refresh_token={access_token}"
    )
    assert response.status_code == 401
    data = response.json()
    assert data["detail"] == "Invalid refresh token"
    assert data["error_code"] == "INVALID_REFRESH_TOKEN_TYPE"

@pytest.mark.asyncio
async def test_google_login_authorize(client: AsyncClient, mock_google_oauth_client):
    # Settings GOOGLE_CLIENT_ID etc., are set in conftest.py now
    response = await client.get(f"{settings.API_V1_STR}/auth/google/login")
    
    assert response.status_code == 200
    data = response.json()
    assert "authorize_url" in data
    assert data["authorize_url"] == "https://mock.google.com/auth?client_id=test" # From mock_google_oauth_client
    mock_google_oauth_client["flow"].authorization_url.assert_called_once() # Corrected assertion

@pytest.mark.asyncio
async def test_google_login_authorize_not_configured(client: AsyncClient):
    original_client_id = settings.GOOGLE_CLIENT_ID
    settings.GOOGLE_CLIENT_ID = None # Simulate not configured
    
    # Temporarily replace the google_flow in auth_service for this test's scope
    # auth.google_flow is initialized at module level, so we patch it there.
    with mock.patch("app.services.auth.google_flow", None):
        response = await client.get(f"{settings.API_V1_STR}/auth/google/login")
    
    settings.GOOGLE_CLIENT_ID = original_client_id # Reset
    
    assert response.status_code == 500
    data = response.json()
    assert data["detail"] == "Google OAuth not configured"
    assert data["error_code"] == "GOOGLE_OAUTH_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_google_callback_new_user(client: AsyncClient, mock_google_oauth_client, mock_user_db, mock_google_id_db):
    # Settings GOOGLE_CLIENT_ID etc., are set in conftest.py
    
    # mock_google_oauth_client["flow"].fetch_token is already a mock.
    # It populates mock_google_oauth_client["flow"].credentials
    # which has mock_google_oauth_client["flow"].credentials.id_token = "mock_google_id_token_string"

    mock_google_oauth_client["verify_id_token"].return_value = { # This is for id_token.verify_oauth2_token
        "sub": "new_google_user_123", # Google subject ID
        "email": "newgoogle@example.com",
        "name": "New Google User",
        "email_verified": True # Often checked
    }

    response = await client.get(f"{settings.API_V1_STR}/auth/google/callback?code=test_auth_code")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    
    mock_google_oauth_client["flow"].fetch_token.assert_called_once_with(code="test_auth_code")
    mock_google_oauth_client["verify_id_token"].assert_called_once_with(
        "mock_google_id_token_string", mock.ANY, settings.GOOGLE_CLIENT_ID
    )
    
    created_user = None
    for user_obj in mock_user_db.values():
        if user_obj.email == "newgoogle@example.com":
            created_user = user_obj
            break
    assert created_user is not None
    assert created_user.google_id == "new_google_user_123"
    assert created_user.full_name == "New Google User"
    assert mock_google_id_db.get("new_google_user_123") is not None

@pytest.mark.asyncio
async def test_google_callback_existing_user_by_google_id(client: AsyncClient, mock_google_oauth_client, test_user_google: User):
    # Settings GOOGLE_CLIENT_ID etc., are set in conftest.py

    mock_google_oauth_client["verify_id_token"].return_value = {
        "sub": test_user_google.google_id, # Existing Google ID
        "email": test_user_google.email,
        "name": test_user_google.full_name,
        "email_verified": True
    }

    response = await client.get(f"{settings.API_V1_STR}/auth/google/callback?code=test_auth_code")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    payload = decode_token(data["access_token"])
    assert payload.sub == test_user_google.id # decode_token returns payload.sub as UUID

    mock_google_oauth_client["flow"].fetch_token.assert_called_once_with(code="test_auth_code")


@pytest.mark.asyncio
async def test_google_callback_link_to_existing_email_user(client: AsyncClient, mock_google_oauth_client, test_user: User, mock_user_db):
    assert test_user.google_id is None # Starts without Google ID
    # Settings GOOGLE_CLIENT_ID etc., are set in conftest.py

    mock_google_oauth_client["verify_id_token"].return_value = {
        "sub": "google_id_for_linking",
        "email": test_user.email, # Existing email
        "name": test_user.full_name,
        "email_verified": True
    }

    response = await client.get(f"{settings.API_V1_STR}/auth/google/callback?code=test_auth_code")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    
    updated_user = mock_user_db.get(test_user.id)
    assert updated_user is not None
    assert updated_user.google_id == "google_id_for_linking"
    mock_google_oauth_client["flow"].fetch_token.assert_called_once_with(code="test_auth_code")


@pytest.mark.asyncio
async def test_google_callback_invalid_code(client: AsyncClient, mock_google_oauth_client):
    # Settings GOOGLE_CLIENT_ID etc., are set in conftest.py
    
    # Simulate error during fetch_token (e.g., Google returns an error for the code)
    mock_google_oauth_client["flow"].fetch_token.side_effect = Exception("Google token error from mock")

    response = await client.get(f"{settings.API_V1_STR}/auth/google/callback?code=invalid_code")
    assert response.status_code == 401
    data = response.json()
    assert "Error obtaining Google token or user info: Google token error from mock" in data["detail"]
    assert data["error_code"] == "GOOGLE_TOKEN_ERROR"
    mock_google_oauth_client["flow"].fetch_token.assert_called_once_with(code="invalid_code")


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, auth_headers_for_user: Dict[str, str]):
    response = await client.post(f"{settings.API_V1_STR}/auth/logout", headers=auth_headers_for_user)
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Successfully logged out (client should delete token)"