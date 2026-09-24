import os
from datetime import datetime, date as date_type
from enum import Enum
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from beanie import Document, init_beanie
from pymongo import AsyncMongoClient

from profiling import check_spending_profile

load_dotenv()

app = FastAPI(title="Profiling Service - Ferdi", version="1.0.0")


# ---------------------------------------------------------------------------
# Model (duplikat minimal dari transaction service, cukup untuk query read-only)
# ---------------------------------------------------------------------------
class TrxType(str, Enum):
    income = "income"
    purchase = "purchase"


class PaymentMethod(str, Enum):
    cash = "cash"
    gopay = "gopay"
    ovo = "ovo"
    shopee = "shopee"
    bni = "bni"
    bca = "bca"
    bri = "bri"
    mandiri = "mandiri"
    dana = "dana"


class Transaction(Document):
    date: datetime
    amount: int
    method: PaymentMethod
    desc: str
    trx_type: TrxType

    class Settings:
        # HARUS SAMA PERSIS dengan nama collection di transaction service
        name = "trx_collection"


@app.on_event("startup")
async def init_db():
    mongo_uri = os.getenv("MONGO_URI")
    db_name = os.getenv("DB_NAME", "bootcamp")

    if not mongo_uri:
        raise ValueError("MONGO_URI tidak ditemukan di Environment Variables!")

    client = AsyncMongoClient(mongo_uri)
    await init_beanie(database=client[db_name], document_models=[Transaction])


@app.get("/")
async def root():
    return {"status": "ok", "message": "Profiling Service Ferdi Berjalan!"}


@app.get("/profile/check")
async def profile_check(check_date: Optional[date_type] = None):
    """
    Endpoint utama profiling, dipanggil oleh transaction service via HTTP
    setiap kali ada transaksi purchase baru.
    """
    target_date = check_date or datetime.now().date()
    return await check_spending_profile(target_date)