from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.db.mongodb_utils import connect_to_mongo, close_mongo_connection
from app.api.v1.router import api_router_v1
from app.utils.exceptions import AppExceptionBase, APIError


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(AppExceptionBase)
async def app_exception_handler(request: Request, exc: AppExceptionBase):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error_code": exc.error_code},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "error_code": "VALIDATION_ERROR"},
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected internal server error occurred.", "error_code": "INTERNAL_SERVER_ERROR"} if settings.DEBUG else {"detail": "Internal Server Error"},
    )


app.include_router(api_router_v1, prefix=settings.API_V1_STR)

@app.get("/", tags=["Root"])
async def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME} API"}

if settings.DEBUG:
    @app.get("/debug-config", tags=["Debug"])
    async def debug_config():
        return {
            "project_name": settings.PROJECT_NAME,
            "database_url_partial": str(settings.DATABASE_URL.with_path("")),
            "database_name": settings.DATABASE_NAME,
            "google_client_id_set": bool(settings.GOOGLE_CLIENT_ID),
            "usdt_wallet_set": bool(settings.USDT_ETH_WALLET_ADDRESS),
            "free_request_limit": settings.FREE_REQUEST_LIMIT,
        }