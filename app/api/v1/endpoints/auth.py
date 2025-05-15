from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Query
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated

from app.schemas.user_schemas import UserCreate, UserResponse, UserLogin
from app.schemas.token_schemas import Token, TokenPayload
from app.services import auth_service
from app.core.dependencies import get_current_active_user
from app.models.user import User
from app.core.security import decode_token
from app.utils.custom_exceptions import AuthError

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user_endpoint(user_in: UserCreate):
    return await auth_service.register_user_email_password(user_in=user_in)

@router.post("/login/email", response_model=Token)
async def login_for_access_token_email(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    return await auth_service.login_email_password(form_data=form_data)

@router.post("/token/refresh", response_model=Token)
async def refresh_token_endpoint(refresh_token: str = Query(..., description="The refresh token")):
    token_payload = decode_token(refresh_token)
    if not token_payload or token_payload.type != "refresh":
        raise AuthError(detail="Invalid refresh token", error_code="INVALID_REFRESH_TOKEN_TYPE")
    return await auth_service.refresh_access_token(token_payload.model_dump())


@router.get("/google/login")
async def google_login_authorize(request: Request):
    authorize_url = await auth_service.get_google_oauth_authorize_url(request)
    return {"authorize_url": authorize_url} # Or RedirectResponse(authorize_url)

@router.get("/google/callback", response_model=Token)
async def google_login_callback(request: Request, code: str = Query(...)):
    # The frontend should ideally exchange this code for tokens by calling this endpoint.
    # Or, if this backend handles the redirect directly:
    # token = await auth_service.handle_google_oauth_callback(request, code)
    # response = RedirectResponse(url="/frontend-redirect-path-after-login") # Redirect to frontend
    # response.set_cookie(key="access_token", value=token.access_token, httponly=True, samesite="lax") # Example for cookies
    # return response
    return await auth_service.handle_google_oauth_callback(request, code)

@router.post("/logout")
async def logout(current_user: Annotated[User, Depends(get_current_active_user)]):
    # For JWT, logout is typically handled client-side by deleting the token.
    # Server-side, you might want to blacklist the token if using a blacklist mechanism.
    # For simplicity, this endpoint just confirms the user was authenticated.
    return {"message": "Successfully logged out (client should delete token)"}