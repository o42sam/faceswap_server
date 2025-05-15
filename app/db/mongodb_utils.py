from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.core.config import settings
from app.models.user import User
from app.models.payment import PaymentAttempt, Subscription

client: AsyncIOMotorClient = None

async def connect_to_mongo():
    global client
    print("Connecting to MongoDB...")
    client = AsyncIOMotorClient(str(settings.DATABASE_URL))
    await init_beanie(
        database=client[settings.DATABASE_NAME],
        document_models=[
            User,
            PaymentAttempt,
            Subscription,
        ]
    )
    print("Successfully connected to MongoDB and initialized Beanie.")

async def close_mongo_connection():
    global client
    if client:
        print("Closing MongoDB connection...")
        client.close()
        print("MongoDB connection closed.")

def get_database_client() -> AsyncIOMotorClient:
    if client is None:
        raise RuntimeError("Database client not initialized. Call connect_to_mongo first.")
    return client