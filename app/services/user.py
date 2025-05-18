from app.models.user import User
from app.schemas.user_schemas import UserResponse
from app.repositories import user as user_repo

async def get_user_profile(user: User) -> UserResponse:
    return UserResponse.model_validate(user)