from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import MongoDsn, AnyHttpUrl
from typing import List, Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "FaceSwap SaaS"
    PROJECT_VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = True

    DATABASE_URL: MongoDsn
    DATABASE_NAME: str

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[AnyHttpUrl] = None

    STRIPE_SECRET_KEY: Optional[str] = None # Keep for now, though not used for new card payments
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None # Keep for now

    PAYSTACK_SECRET_KEY: Optional[str] = None
    PAYSTACK_PUBLIC_KEY: Optional[str] = None # For frontend if needed

    USDT_ETH_WALLET_ADDRESS: Optional[str] = None
    
    ONE_TIME_PAYMENT_AMOUNT_USD: int = 2999 # Price in cents
    MONTHLY_SUBSCRIPTION_AMOUNT_USD: int = 299 # Price in cents
    MONTHLY_REQUEST_LIMIT: int = 40
    FREE_REQUEST_LIMIT: int = 1

    # Paystack API Base URL
    PAYSTACK_API_URL: str = "https://api.paystack.co"


    model_config = SettingsConfigDict(env_file=".env", extra='ignore')

settings = Settings()