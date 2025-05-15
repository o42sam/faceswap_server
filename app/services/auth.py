from fastapi import HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from httpx_oauth.google import GoogleOAuth2
from httpx_oauth.oauth2 import OAuth2Token
from typing import Optional

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, verify_password
from app.crud import crud_user
from app.schemas.user_schemas import UserCreate, UserCreateGoogle, UserResponse
from app.schemas.token_schemas import Token
from app.models.user import User
from app.utils.custom_exceptions import AuthError, DuplicateResourceError, AppLogicError

google_oauth_client = None
if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
    google_oauth_client = GoogleOAuth2(
        settings.GOOGLE_CLIENT_ID,
        settings.GOOGLE_CLIENT_SECRET
    )

async def register_user_email_password(user_in: UserCreate) -> UserResponse:
    existing_user = await crud_user.get_user_by_email(email=user_in.email)
    if existing_user:
        raise DuplicateResourceError(detail="User with this email already exists", error_code="EMAIL_EXISTS")
    
    user = await crud_user.create_user(user_in=user_in)
    return UserResponse.model_validate(user)

async def login_email_password(form_data: OAuth2PasswordRequestForm) -> Token:
    user = await crud_user.get_user_by_email(email=form_data.username)
    if not user or not user.hashed_password: # No password for OAuth users initially
        raise AuthError(detail="Incorrect email or password (user may have registered with Google)", error_code="LOGIN_INVALID_CREDENTIALS")
    
    if not verify_password(form_data.password, user.hashed_password):
        raise AuthError(detail="Incorrect email or password", error_code="LOGIN_INVALID_CREDENTIALS")
    
    if not user.is_active:
        raise AuthError(detail="Inactive user", error_code="INACTIVE_USER")

    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)
    return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer")

async def refresh_access_token(refresh_token_payload: dict) -> Token:
    user_id = refresh_token_payload.get("sub")
    if not user_id:
        raise AuthError(detail="Invalid refresh token", error_code="INVALID_REFRESH_TOKEN")
    
    user = await crud_user.get_user_by_id(user_id)
    if not user or not user.is_active:
        raise AuthError(detail="User not found or inactive", error_code="USER_NOT_FOUND_OR_INACTIVE")

    new_access_token = create_access_token(subject=user.id)
    # Optionally, issue a new refresh token or keep the old one
    new_refresh_token = create_refresh_token(subject=user.id) # Example: issue new one
    
    return Token(access_token=new_access_token, refresh_token=new_refresh_token, token_type="bearer")


async def get_google_oauth_authorize_url(request: Request) -> str:
    if not google_oauth_client:
        raise AppLogicError(detail="Google OAuth not configured", error_code="GOOGLE_OAUTH_NOT_CONFIGURED")
    redirect_uri = str(settings.GOOGLE_REDIRECT_URI)
    return await google_oauth_client.get_authorize_redirect(request, redirect_uri, scope=["email", "profile"])


async def handle_google_oauth_callback(request: Request, code: str) -> Token:
    if not google_oauth_client:
        raise AppLogicError(detail="Google OAuth not configured", error_code="GOOGLE_OAUTH_NOT_CONFIGURED")
    
    redirect_uri = str(settings.GOOGLE_REDIRECT_URI)
    try:
        token_data: OAuth2Token = await google_oauth_client.get_access_token(request, code, redirect_uri)
    except Exception as e:
        raise AuthError(detail=f"Error obtaining Google token: {str(e)}", error_code="GOOGLE_TOKEN_ERROR")

    user_info = await google_oauth_client.get_id_email(token_data["access_token"])
    google_id = user_info.get("id")
    email = user_info.get("email")
    full_name = user_info.get("name") or user_info.get("given_name") # Or parse from profile

    if not email or not google_id:
        raise AuthError(detail="Could not retrieve email or ID from Google", error_code="GOOGLE_INFO_MISSING")

    user = await crud_user.get_user_by_google_id(google_id)
    if not user:
        user = await crud_user.get_user_by_email(email)
        if user: # Existing email user, link Google ID
            if user.google_id is None:
                user.google_id = google_id
                await user.save()
            elif user.google_id != google_id: # Should not happen if email is primary key for Google
                 raise AuthError(detail="Email already associated with a different Google account.", error_code="EMAIL_GOOGLE_MISMATCH")
        else: # New user via Google
            user_create_google = UserCreateGoogle(email=email, google_id=google_id, full_name=full_name)
            user = await crud_user.create_user_google(user_in=user_create_google)
    
    if not user.is_active:
         raise AuthError(detail="User account is inactive.", error_code="INACTIVE_USER_GOOGLE")

    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)
    return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer")