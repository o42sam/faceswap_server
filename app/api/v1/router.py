from fastapi import APIRouter

from app.api.v1.endpoints import auth, user, payment, faceswap

api_router_v1 = APIRouter()

api_router_v1.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router_v1.include_router(user.router, prefix="/users", tags=["Users"])
api_router_v1.include_router(payment.router, prefix="/payments", tags=["Payments & Subscriptions"])
api_router_v1.include_router(faceswap.router, prefix="/faceswap", tags=["FaceSwap Service"])