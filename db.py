import os
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.database import Database

class MongoDB:
    _client: AsyncIOMotorClient = None
    _db: Database = None

    @classmethod
    def get_client(cls) -> AsyncIOMotorClient:
        if cls._client is None:
            cls._client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
        return cls._client

    @classmethod
    def get_db(cls) -> Database:
        if cls._db is None:
            cls._db = cls.get_client()["BHU_Bot"]
        return cls._db

# Usage example: 
# db = MongoDB.get_db()
# print(db.client.__str__())
# models_collection = db["models"]
