import random
from calendar import monthrange
from datetime import datetime, date as date_type
from typing import Optional


async def get_historical_monthly_breakdown(current_year: int, current_month: int) -> list[dict]:
    """
    Ambil rincian pengeluaran per bulan dari histori (bulan-bulan sebelum bulan berjalan),
    diurutkan dari yang terlama ke terbaru.
    """
    from main import Transaction, TrxType  # lazy import, hindari circular import dengan main.py

    pipeline = [
        {
            "$match": {
                "trx_type": TrxType.purchase.value,  # pemasukan diabaikan
                "date": {"$lt": datetime(current_year, current_month, 1)},
            }
        },
        {
            "$group": {
                "_id": {"year": {"$year": "$date"}, "month": {"$month": "$date"}},
                "total": {"$sum": "$amount"},
            }
        },
        {"$sort": {"_id.year": 1, "_id.month": 1}},
    ]
    results = await Transaction.aggregate(pipeline).to_list()
    return [
        {"year": r["_id"]["year"], "month": r["_id"]["month"], "total": r["total"]}
        for r in results
    ]


async def get_historical_monthly_average(current_year: int, current_month: int) -> Optional[float]:
    """
    Hitung x = rata-rata pengeluaran per bulan dari bulan-bulan sebelumnya.
    Return None kalau belum ada histori sama sekali (bulan pertama pakai app).
    """
    breakdown = await get_historical_monthly_breakdown(current_year, current_month)

    if not breakdown:
        return None

    total = sum(r["total"] for r in breakdown)
    return total / len(breakdown)


async def get_current_month_spending(up_to_date: date_type) -> float:
    """
    Hitung y = total pengeluaran bulan berjalan, dari tanggal 1 s.d. up_to_date.
    """
    from main import Transaction, TrxType  # lazy import, hindari circular import dengan main.py

    start_of_month = datetime(up_to_date.year, up_to_date.month, 1)
    end_of_range = datetime(up_to_date.year, up_to_date.month, up_to_date.day, 23, 59, 59)

    pipeline = [
        {
            "$match": {
                "trx_type": TrxType.purchase.value,
                "date": {"$gte": start_of_month, "$lte": end_of_range},
            }
        },
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]
    result = await Transaction.aggregate(pipeline).to_list()
    return result[0]["total"] if result else 0.0


async def get_breakdown_by_method(up_to_date: date_type) -> list[dict]:
    """
    Rincian pengeluaran bulan berjalan per metode pembayaran, dari yang terbesar.
    """
    from main import Transaction, TrxType  # lazy import, hindari circular import dengan main.py

    start_of_month = datetime(up_to_date.year, up_to_date.month, 1)
    end_of_range = datetime(up_to_date.year, up_to_date.month, up_to_date.day, 23, 59, 59)

    pipeline = [
        {
            "$match": {
                "trx_type": TrxType.purchase.value,
                "date": {"$gte": start_of_month, "$lte": end_of_range},
            }
        },
        {"$group": {"_id": "$method", "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}},
    ]
    results = await Transaction.aggregate(pipeline).to_list()
    grand_total = sum(r["total"] for r in results) or 1  # hindari divide by zero

    return [
        {
            "method": r["_id"],
            "total": r["total"],
            "count": r["count"],
            "percentage": round(r["total"] / grand_total * 100, 1),
        }
        for r in results
    ]


def project_month_end_total(y: float, up_to_date: date_type) -> float:
    """
    Proyeksi total pengeluaran akhir bulan, dengan asumsi laju harian sama seperti sejauh ini.
    """
    days_elapsed = up_to_date.day
    total_days_in_month = monthrange(up_to_date.year, up_to_date.month)[1]

    if days_elapsed == 0:
        return 0.0

    daily_average = y / days_elapsed
    return round(daily_average * total_days_in_month, 2)


def get_motivational_message(x: float, y: float, persen: float) -> str:
    """
    Pesan warning yang santai dan memotivasi, bukan kaku. Intensitas pesan
    disesuaikan dengan seberapa jauh sudah melebihi rata-rata.
    """
    if persen >= 50:
        messages = [
            f"Waduh, udah {persen:.0f}% di atas rata-rata biasanya nih! Yuk coba direm dulu sisa bulan ini, kamu pasti bisa kok 💪",
            f"Dompet lagi kencang napasnya, {persen:.0f}% di atas kebiasaan. Coba pause dulu belanja yang gak urgent ya!",
        ]
    else:
        messages = [
            "Semangat! Kamu udah lewat rata-rata pengeluaran bulanan. Gapapa, masih ada waktu buat lebih hemat sisa bulan ini.",
            "Eits, dompet mulai teriak nih! Pengeluaran udah ngelewatin biasanya. Coba deh cek lagi mana yang bisa dihemat ya!",
        ]
    return random.choice(messages)


async def check_spending_profile(on_date: date_type) -> dict:
    """
    Fungsi utama profiling summary, dipanggil setiap kali transaksi purchase baru dicatat.
    Mengembalikan insight lengkap: status, breakdown per metode, tren histori, dan proyeksi.
    """
    historical_breakdown = await get_historical_monthly_breakdown(on_date.year, on_date.month)

    if not historical_breakdown:
        return {
            "status": "no_baseline",
            "message": "Belum ada cukup histori bulan sebelumnya untuk profiling.",
        }

    x = sum(r["total"] for r in historical_breakdown) / len(historical_breakdown)
    y = await get_current_month_spending(on_date)

    breakdown_by_method = await get_breakdown_by_method(on_date)
    projected_total = project_month_end_total(y, on_date)

    days_elapsed = on_date.day
    total_days_in_month = monthrange(on_date.year, on_date.month)[1]
    daily_average_this_month = round(y / days_elapsed, 2) if days_elapsed else 0.0

    base_result = {
        "x": round(x, 2),
        "y": y,
        "days_elapsed": days_elapsed,
        "total_days_in_month": total_days_in_month,
        "daily_average_this_month": daily_average_this_month,
        "projected_month_end_total": projected_total,
        "breakdown_by_method": breakdown_by_method,
        "historical_monthly_totals": historical_breakdown,
    }

    if x >= y:
        base_result.update({
            "status": "safe",
            "message": "Masih aman, pengeluaran bulan ini masih di bawah rata-rata.",
        })
        return base_result

    persen = (y - x) / x * 100 if x > 0 else 0
    base_result.update({
        "status": "alert",
        "percentage_over_average": round(persen, 1),
        "message": get_motivational_message(x, y, persen),
    })
    return base_result

