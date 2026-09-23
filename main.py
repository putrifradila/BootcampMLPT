import io
import os
from datetime import datetime, date as date_type
from enum import Enum
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from beanie import Document, PydanticObjectId, init_beanie
from pymongo import AsyncMongoClient

# Load environment variables dari file .env
load_dotenv()

app = FastAPI(title="Aplikasi Catatan Keuangan Ferdi", version="1.0.0")

@app.get("/")
async def root():
    return {"status": "ok", "message": "API Catatan Keuangan Ferdi Berjalan!"}

# ---------------------------------------------------------------------------
# Enum & Model Data
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
        name = "trx_collection"


# ---------------------------------------------------------------------------
# Schema Pydantic Request
# ---------------------------------------------------------------------------
class RequestNewTransaction(BaseModel):
    amount: int = Field(ge=1, description="Amount transaksi. Minimum Rp1, tidak ada batas maksimum.")
    method: PaymentMethod
    desc: str
    trx_type: TrxType
    date: Optional[date_type] = Field(
        default=None,
        description="Tanggal transaksi, format YYYY-MM-DD (tanpa jam). Kalau tidak diisi, otomatis pakai tanggal saat request dikirim.",
    )


class RequestUpdateTransaction(BaseModel):
    amount: Optional[int] = Field(default=None, ge=1, description="Amount transaksi. Minimum Rp1.")
    method: Optional[PaymentMethod] = None
    desc: Optional[str] = None
    trx_type: Optional[TrxType] = None
    date: Optional[date_type] = None


# ---------------------------------------------------------------------------
# Startup & Exception Handler
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def init_db():
    # Ambil MONGO_URI dan DB_NAME dari file .env atau OpenShift Secret
    mongo_uri = os.getenv("MONGO_URI")
    db_name = os.getenv("DB_NAME", "bootcamp")

    if not mongo_uri:
        raise ValueError("MONGO_URI tidak ditemukan di Environment Variables!")

    client = AsyncMongoClient(mongo_uri)
    await init_beanie(database=client[db_name], document_models=[Transaction])


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        field_path = ".".join(str(loc) for loc in err["loc"] if loc != "body")
        errors.append({"field": field_path, "message": err["msg"]})
 
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Input tidak valid",
            "errors": errors,
        },
    )


# ---------------------------------------------------------------------------
# CRUD Endpoints
# ---------------------------------------------------------------------------
@app.post("/transaction/add")
async def add_transaction(request_body: RequestNewTransaction):
    trx_date = (
        datetime.combine(request_body.date, datetime.min.time())
        if request_body.date
        else datetime.now()
    )
    trx = Transaction(
        date=trx_date,
        amount=request_body.amount,
        method=request_body.method,
        desc=request_body.desc,
        trx_type=request_body.trx_type,
    )
    await trx.insert()
    return trx


@app.get("/transaction")
async def get_transaction(start_date: datetime, end_date: datetime):
    return await Transaction.find(
        Transaction.date >= start_date, Transaction.date <= end_date
    ).to_list()


@app.get("/transaction/summary")
async def summary_by_method(year: int, month: int):
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)

    pipeline = [
        {"$match": {"date": {"$gte": start, "$lt": end}}},
        {
            "$group": {
                "_id": "$trx_type",
                "total_amount": {"$sum": "$amount"},
                "count": {"$sum": 1},
            }
        },
    ]

    return await Transaction.aggregate(pipeline).to_list()


# ---------------------------------------------------------------------------
# Insight Keuangan
# ---------------------------------------------------------------------------
@app.get("/transaction/insight")
async def get_insight(year: int, month: int):
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)

    pipeline = [
        {"$match": {"date": {"$gte": start, "$lt": end}}},
        {
            "$group": {
                "_id": "$trx_type",
                "total_amount": {"$sum": "$amount"},
                "count": {"$sum": 1},
            }
        },
    ]

    raw_summary = await Transaction.aggregate(pipeline).to_list()

    income_total = 0
    purchase_total = 0
    for row in raw_summary:
        if row["_id"] == TrxType.income.value:
            income_total = row["total_amount"]
        elif row["_id"] == TrxType.purchase.value:
            purchase_total = row["total_amount"]

    net_amount = income_total - purchase_total

    if income_total == 0:
        spend_ratio: Optional[float] = None
        if purchase_total == 0:
            label = "No transactions recorded this month"
        else:
            label = "Reckless Spender"
    else:
        spend_ratio = purchase_total / income_total
        if spend_ratio >= 0.70:
            label = "Reckless Spender"
        elif spend_ratio >= 0.40:
            label = "Indikasi Big Spender"
        else:
            label = "Big Saver"

    return {
        "year": year,
        "month": month,
        "income_total": income_total,
        "purchase_total": purchase_total,
        "net_amount": net_amount,
        "spend_ratio": spend_ratio,
        "label": label,
        "summary_per_type": raw_summary,
    }


@app.get("/transaction/{trx_id}")
async def get_transaction_by_id(trx_id: PydanticObjectId):
    trx = await Transaction.get(trx_id)
    if not trx:
        raise HTTPException(status_code=404, detail=f"Transaksi dengan id {trx_id} tidak ditemukan")
    return trx
 
 
@app.put("/transaction/{trx_id}")
async def update_transaction(trx_id: PydanticObjectId, request_body: RequestUpdateTransaction):
    trx = await Transaction.get(trx_id)
    if not trx:
        raise HTTPException(status_code=404, detail=f"Transaksi dengan id {trx_id} tidak ditemukan")
 
    update_data = request_body.model_dump(exclude_unset=True, exclude_none=True)
 
    if "date" in update_data and update_data["date"] is not None:
        update_data["date"] = datetime.combine(update_data["date"], datetime.min.time())
 
    for field, value in update_data.items():
        setattr(trx, field, value)
 
    await trx.save()
    return trx


@app.delete("/transaction/{trx_id}")
async def delete_transaction(trx_id: PydanticObjectId):
    trx = await Transaction.get(trx_id)
    if trx is None:
        raise HTTPException(404, f"Transaksi dengan id {trx_id} tidak ditemukan")
    await trx.delete()
    return {"status": "sukses", "message": f"Transaksi {trx_id} berhasil dihapus"}
    

# ---------------------------------------------------------------------------
# Migrasi Excel
# ---------------------------------------------------------------------------
REQUIRED_COLUMNS = {"datetime", "amount", "payment_method", "description"}

@app.post("/transaction/import-excel")
async def import_excel(file: UploadFile = File(...), dry_run: bool = False):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File harus berformat .xlsx atau .xls")

    try:
        content = await file.read()
        df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"File Excel tidak bisa dibaca: {e}")

    df.columns = [str(c).strip().lower() for c in df.columns]

    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Kolom berikut tidak ditemukan di excel: {sorted(missing_columns)}",
        )

    valid_transactions = []
    failed_rows = []

    for idx, row in df.iterrows():
        excel_row_number = idx + 2
        try:
            raw_date = row["datetime"]
            if pd.isna(raw_date):
                raise ValueError("Tanggal tidak boleh kosong")
            trx_date = pd.to_datetime(raw_date).to_pydatetime()

            raw_amount_str = str(row["amount"]).strip()
            cleaned_str = raw_amount_str.replace("Rp", "").replace(".", "").replace(",", "").strip()
            
            is_negative = cleaned_str.startswith("-")
            if is_negative:
                cleaned_str = cleaned_str.lstrip("-")

            if not cleaned_str.isdigit():
                raise ValueError(f"Format amount tidak valid: {raw_amount_str}")

            amount_val = int(cleaned_str)
            if amount_val < 1:
                raise ValueError("Amount harus minimal 1")

            trx_type = TrxType.purchase if is_negative else TrxType.income
            method = PaymentMethod(str(row["payment_method"]).strip().lower())
            desc = str(row["description"]).strip()

            valid_transactions.append(
                Transaction(
                    date=trx_date,
                    amount=amount_val,
                    method=method,
                    desc=desc,
                    trx_type=trx_type,
                )
            )
        except Exception as e:
            failed_rows.append({"row": excel_row_number, "reason": str(e)})

    if valid_transactions and not dry_run:
        await Transaction.insert_many(valid_transactions)

    return {
        "status": "sukses" if not failed_rows else "sebagian gagal",
        "dry_run": dry_run,
        "total_rows_in_file": len(df),
        "success_count": 0 if dry_run else len(valid_transactions),
        "ready_to_import": len(valid_transactions) if dry_run else None,
        "failed_count": len(failed_rows),
        "failed_rows": failed_rows,
    }