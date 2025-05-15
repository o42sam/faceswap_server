from fastapi import APIRouter

from app.api.v1.endpoints import auth, users, payments, faceswap

api_router_v1 = APIRouter()

api_router_v1.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router_v1.include_router(users.router, prefix="/users", tags=["Users"])
api_router_v1.include_router(payments.router, prefix="/payments", tags=["Payments & Subscriptions"])
api_router_v1.include_router(faceswap.router, prefix="/faceswap", tags=["FaceSwap Service"])