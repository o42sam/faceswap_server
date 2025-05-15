from app.models.user import User
from app.schemas.user_schemas import UserResponse
from app.crud import crud_user

async def get_user_profile(user: User) -> UserResponse:
    return UserResponse.model_validate(user)