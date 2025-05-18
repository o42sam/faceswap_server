from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from typing import Optional, Annotated

from app.core.security import decode_token
from app.schemas.token_schemas import TokenPayload
from app.models.user import User
from app.repositories.user import get_user_by_id
from app.utils.exceptions import AuthError, ForbiddenError, PaymentRequiredError
from app.core.config import settings
from datetime import datetime

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login/email")

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    token_payload = decode_token(token)
    if not token_payload or token_payload.type != "access":
        raise AuthError(detail="Invalid access token", error_code="INVALID_ACCESS_TOKEN")
    
    user = await get_user_by_id(user_id=token_payload.sub)
    if not user:
        raise AuthError(detail="User not found", error_code="USER_NOT_FOUND")
    if not user.is_active:
        raise ForbiddenError(detail="Inactive user", error_code="INACTIVE_USER")
    return user

async def get_current_active_user(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user


class FaceSwapAccessChecker:
    def __init__(self, required: bool = True):
        self.required = required

    async def __call__(self, current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
        if not self.required:
            return current_user

        is_paid_user = current_user.subscription_type == "one_time" or \
                       (current_user.subscription_type == "monthly" and \
                        current_user.subscription_end_date and \
                        current_user.subscription_end_date > datetime.utcnow())

        if is_paid_user:
            if current_user.subscription_type == "monthly":
                if current_user.monthly_requests_used >= settings.MONTHLY_REQUEST_LIMIT:
                    raise PaymentRequiredError(
                        detail="Monthly request limit reached. Please wait for the next cycle or upgrade.",
                        error_code="MONTHLY_LIMIT_REACHED"
                    )
            return current_user

        if current_user.free_requests_used >= settings.FREE_REQUEST_LIMIT:
            raise PaymentRequiredError(
                detail=f"Free request limit of {settings.FREE_REQUEST_LIMIT} reached. Please subscribe for continued use.",
                error_code="FREE_LIMIT_REACHED_PAYMENT_REQUIRED"
            )
        
        return current_user