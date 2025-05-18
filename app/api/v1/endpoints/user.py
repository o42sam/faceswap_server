from fastapi import APIRouter, Depends
from typing import Annotated

from app.schemas.user_schemas import UserResponse
from app.services import user
from app.core.dependencies import get_current_active_user
from app.models.user import User

router = APIRouter()

@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: Annotated[User, Depends(get_current_active_user)]):
    return await user.get_user_profile(user=current_user)