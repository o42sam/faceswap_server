from typing import Optional, Union
import uuid
from beanie.exceptions import DocumentNotFound
from datetime import datetime

from app.models.user import User
from app.schemas.user_schemas import UserCreate, UserCreateGoogle, UserUpdate
from app.core.security import get_password_hash

async def get_user_by_email(email: str) -> Optional[User]:
    return await User.find_one(User.email == email)

async def get_user_by_id(user_id: Union[str, uuid.UUID]) -> Optional[User]:
    if isinstance(user_id, str):
        try:
            user_id = uuid.UUID(user_id)
        except ValueError:
            return None # Invalid UUID format
    return await User.get(user_id)
    
async def get_user_by_google_id(google_id: str) -> Optional[User]:
    return await User.find_one(User.google_id == google_id)

async def create_user(user_in: UserCreate) -> User:
    hashed_password = get_password_hash(user_in.password)
    user = User(
        email=user_in.email.lower(),
        hashed_password=hashed_password,
        full_name=user_in.full_name,
    )
    await user.insert()
    return user

async def create_user_google(user_in: UserCreateGoogle) -> User:
    user = User(
        email=user_in.email.lower(),
        google_id=user_in.google_id,
        full_name=user_in.full_name,
        is_active=True # Assuming Google verified email
    )
    await user.insert()
    return user
    
async def update_user(user: User, user_in: UserUpdate) -> User:
    if user_in.email:
        user.email = user_in.email.lower()
    if user_in.full_name:
        user.full_name = user_in.full_name
    if user_in.password:
        user.hashed_password = get_password_hash(user_in.password)
    await user.save()
    return user

async def increment_user_request_count(user: User, is_free_request: bool):
    if is_free_request:
        user.free_requests_used += 1
    else: # Paid request (monthly)
        user.monthly_requests_used += 1
    user.last_request_date = datetime.utcnow()
    await user.save()

async def reset_monthly_user_request_count(user: User):
    user.monthly_requests_used = 0
    await user.save()