import os

from dotenv import load_dotenv
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

load_dotenv()

_client: AsyncMongoClient | None = None
_db: AsyncDatabase | None = None


async def connect() -> None:
    global _client, _db
    uri = os.environ["MONGODB_URI"]
    _client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000)
    # Database name comes from the URI path (mongodb://host:27017/dbname), or MONGODB_DB.
    default = _client.get_default_database(os.getenv("MONGODB_DB"))
    _db = default
    await _client.admin.command("ping")


async def close() -> None:
    if _client is not None:
        await _client.close()


def get_db() -> AsyncDatabase:
    if _db is None:
        raise RuntimeError("Database not connected")
    return _db
