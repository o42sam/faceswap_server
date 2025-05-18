from fastapi import HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from google_auth_oauthlib.flow import Flow # Replaced httpx_oauth.google
from google.oauth2 import id_token # For verifying Google ID token
from google.auth.transport.requests import Request as GoogleAuthRequest # For verifying Google ID token

from typing import Optional
import json # For loading client secrets if stored as JSON

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, verify_password
from app.repositories import user as user_repo
from app.schemas.user_schemas import UserCreate, UserCreateGoogle, UserResponse
from app.schemas.token_schemas import Token
from app.models.user import User
from app.utils.exceptions import AuthError, DuplicateResourceError, AppLogicError

# google_oauth_client = None # Replaced by flow object initialization

# --- Start of new Google OAuth setup using google-auth-oauthlib ---
google_flow = None
if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
    # Option 1: If you have client_secret.json file (recommended by Google)
    # try:
    #     google_flow = Flow.from_client_secrets_file(
    #         settings.GOOGLE_CLIENT_SECRET_FILE_PATH, # e.g., "client_secret.json"
    #         scopes=['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile'],
    #         redirect_uri=str(settings.GOOGLE_REDIRECT_URI)
    #     )
    # except FileNotFoundError:
    #     google_flow = None # Or raise configuration error

    # Option 2: If you have client ID and secret directly (less common for Flow object but possible)
    # For this setup, you'd typically construct the client_config dictionary manually.
    # This is more aligned if you were using google.oauth2.credentials.Credentials directly
    # With Flow, it's usually easier to just use the client_secret.json.
    # However, we can adapt it if GOOGLE_CLIENT_SECRET is the actual secret string
    # and not a path to a file.
    # If GOOGLE_CLIENT_SECRET is the secret string itself:
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            # "redirect_uris": [str(settings.GOOGLE_REDIRECT_URI)], # redirect_uri is set in Flow constructor
            # "javascript_origins": ["http://localhost:3000"] # Optional: for client-side apps
        }
    }
    try:
        google_flow = Flow.from_client_config(
            client_config,
            scopes=['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile'],
            redirect_uri=str(settings.GOOGLE_REDIRECT_URI)
        )
    except Exception as e:
        # Handle potential errors during Flow initialization if config is malformed
        # For simplicity, we'll just print an error or log it
        print(f"Error initializing Google OAuth Flow: {e}")
        google_flow = None
# --- End of new Google OAuth setup ---


async def register_user_email_password(user_in: UserCreate) -> UserResponse:
    existing_user = await user_repo.get_user_by_email(email=user_in.email)
    if existing_user:
        raise DuplicateResourceError(detail="User with this email already exists", error_code="EMAIL_EXISTS")
    
    user = await user_repo.create_user(user_in=user_in)
    return UserResponse.model_validate(user)

async def login_email_password(form_data: OAuth2PasswordRequestForm) -> Token:
    user = await user_repo.get_user_by_email(email=form_data.username)
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
    
    user = await user_repo.get_user_by_id(user_id)
    if not user or not user.is_active:
        raise AuthError(detail="User not found or inactive", error_code="USER_NOT_FOUND_OR_INACTIVE")

    new_access_token = create_access_token(subject=user.id)
    new_refresh_token = create_refresh_token(subject=user.id) 
    
    return Token(access_token=new_access_token, refresh_token=new_refresh_token, token_type="bearer")


async def get_google_oauth_authorize_url(request: Request) -> str: # Request might not be needed if state is handled differently
    if not google_flow:
        raise AppLogicError(detail="Google OAuth not configured", error_code="GOOGLE_OAUTH_NOT_CONFIGURED")
    
    # The 'state' parameter is recommended for preventing CSRF attacks.
    # You might want to generate and store it in the session or a temporary cache.
    # For simplicity, this example doesn't implement state storage and verification fully.
    # authorization_url, state = google_flow.authorization_url(access_type='offline', prompt='consent')
    authorization_url, _ = google_flow.authorization_url(
        # access_type='offline' to get a refresh token, if needed for Google APIs.
        # For just login, it might not be necessary to store Google's refresh token.
        # prompt='consent' to ensure the user sees the consent screen.
    )
    # Store state in session or cache here if you generate it: request.session['oauth_state'] = state
    return authorization_url


async def handle_google_oauth_callback(request: Request, code: str) -> Token: # `request` is needed to reconstruct the full callback URL
    if not google_flow:
        raise AppLogicError(detail="Google OAuth not configured", error_code="GOOGLE_OAUTH_NOT_CONFIGURED")

    # It's important that the redirect_uri used here is *exactly* the same as the one
    # used to generate the authorization URL and configured in Google Cloud Console.
    # The Flow object already has it configured.

    # If you used 'state' in get_google_oauth_authorize_url, you should retrieve and verify it here.
    # stored_state = request.session.pop('oauth_state', None)
    # received_state = request.query_params.get('state')
    # if not stored_state or stored_state != received_state:
    #     raise AuthError(detail="OAuth state mismatch, possible CSRF attack.", error_code="GOOGLE_OAUTH_STATE_MISMATCH")

    try:
        # Reconstruct the full callback URL that Google redirected to.
        # This is sometimes required by the OAuth library.
        full_callback_url = str(request.url)
        
        # Exchange the authorization code for an access token and ID token
        google_flow.fetch_token(code=code) # For server-side flow with code
        # Or if you are passing the full authorization response URL:
        # google_flow.fetch_token(authorization_response=full_callback_url)

        credentials = google_flow.credentials
        
        # Verify the ID token and get user info
        # The ID token is JWT signed by Google and contains user information.
        id_info = id_token.verify_oauth2_token(
            credentials.id_token, GoogleAuthRequest(), settings.GOOGLE_CLIENT_ID
        )

    except ValueError as e: # google.oauth2.id_token.verify_oauth2_token can raise ValueError
        raise AuthError(detail=f"Invalid Google ID token: {str(e)}", error_code="GOOGLE_ID_TOKEN_INVALID")
    except Exception as e:
        # This catches errors from fetch_token (e.g., invalid code, token fetch failed)
        raise AuthError(detail=f"Error obtaining Google token or user info: {str(e)}", error_code="GOOGLE_TOKEN_ERROR")

    google_id = id_info.get("sub") # 'sub' is the standard claim for user ID
    email = id_info.get("email")
    full_name = id_info.get("name")
    # email_verified = id_info.get("email_verified") # You might want to check this

    if not email or not google_id:
        raise AuthError(detail="Could not retrieve email or ID from Google token", error_code="GOOGLE_INFO_MISSING")

    # if not email_verified:
    #     raise AuthError(detail="Google email not verified", error_code="GOOGLE_EMAIL_NOT_VERIFIED")

    user = await user_repo.get_user_by_google_id(google_id)
    if not user:
        user = await user_repo.get_user_by_email(email)
        if user: # Existing email user, link Google ID
            if user.google_id is None:
                user.google_id = google_id
                # If you store name and it might differ, update it:
                # if full_name and user.full_name != full_name:
                #     user.full_name = full_name
                await user.save()
            elif user.google_id != google_id: 
                raise AuthError(detail="Email already associated with a different Google account.", error_code="EMAIL_GOOGLE_MISMATCH")
        else: # New user via Google
            user_create_google = UserCreateGoogle(email=email, google_id=google_id, full_name=full_name)
            user = await user_repo.create_user_google(user_in=user_create_google)
    
    if not user.is_active:
        raise AuthError(detail="User account is inactive.", error_code="INACTIVE_USER_GOOGLE")

    # Generate your application's tokens
    app_access_token = create_access_token(subject=user.id)
    app_refresh_token = create_refresh_token(subject=user.id)
    
    return Token(access_token=app_access_token, refresh_token=app_refresh_token, token_type="bearer")