import pytest
from httpx import AsyncClient
from typing import Dict

from app.core.config import settings
from app.models.user import User # Import User model

@pytest.mark.asyncio
async def test_read_users_me_success(client: AsyncClient, test_user: User, auth_headers_for_user: Dict[str, str]):
    response = await client.get(f"{settings.API_V1_STR}/users/me", headers=auth_headers_for_user)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user.email
    assert data["id"] == str(test_user.id)
    assert data["full_name"] == test_user.full_name
    assert data["subscription_type"] == test_user.subscription_type

@pytest.mark.asyncio
async def test_read_users_me_no_auth(client: AsyncClient):
    response = await client.get(f"{settings.API_V1_STR}/users/me")
    assert response.status_code == 401 # Depends on how FastAPI handles missing OAuth2 token
    data = response.json()
    assert data["detail"] == "Not authenticated" # Default FastAPI message for missing token

@pytest.mark.asyncio
async def test_read_users_me_invalid_token(client: AsyncClient):
    headers = {"Authorization": "Bearer invalidtoken"}
    response = await client.get(f"{settings.API_V1_STR}/users/me", headers=headers)
    assert response.status_code == 401 # AuthError from decode_token
    data = response.json()
    assert data["error_code"] == "INVALID_TOKEN"