from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from pymongo.errors import OperationFailure
from app.core.config import settings   # ✅ FIXED IMPORT

client: AsyncIOMotorClient | None = None


async def _safe_create_index(collection, keys, **kwargs):
    try:
        await collection.create_index(keys, **kwargs)
    except OperationFailure as exc:
        if getattr(exc, "code", None) == 85 and "already exists" in str(exc):
            return
        raise


def get_client() -> AsyncIOMotorClient:
    global client
    if client is None:
        print("✅ Connecting to MongoDB at:", settings.MONGODB_URI)
        client = AsyncIOMotorClient(settings.MONGODB_URI)
    return client


async def get_db():
    return get_client()[settings.MONGODB_DB]


async def init_indexes():
    print("🚀 Initializing MongoDB indexes...")
    db = await get_db()

    # Users
    await _safe_create_index(db.users, [("email", ASCENDING)], unique=True, name="uniq_email")
    await _safe_create_index(db.users, [("pan_number", ASCENDING)], unique=True, sparse=True, name="uniq_pan_number")

    # Staff
    await _safe_create_index(db.staff_users, [("email", ASCENDING)], unique=True, name="uniq_staff_email")
    await _safe_create_index(db.staff_users, [("role", ASCENDING)], name="staff_role_idx")

    # Bank
    await _safe_create_index(db.bank_accounts, [("account_number", ASCENDING)], unique=True, name="uniq_account")

    # Loans
    await _safe_create_index(db.personal_loans, [("customer_id", ASCENDING)])
    await _safe_create_index(db.vehicle_loans, [("customer_id", ASCENDING)])
    await _safe_create_index(db.education_loans, [("customer_id", ASCENDING)])
    await _safe_create_index(db.home_loans, [("customer_id", ASCENDING)])

    # Transactions
    await _safe_create_index(db.transactions, [("customer_id", ASCENDING)])
    await _safe_create_index(db.transactions, [("loan_id", ASCENDING)])

    # KYC
    await _safe_create_index(db.kyc_details, [("customer_id", ASCENDING)], unique=True)
    await _safe_create_index(
        db.kyc_details,
        [("aadhaar_number", ASCENDING)],
        unique=True,
        sparse=True,
    )

    # EMI
    await _safe_create_index(db.emi_schedules, [("loan_id", ASCENDING)])
    await _safe_create_index(db.emi_schedules, [("customer_id", ASCENDING)])
    await _safe_create_index(db.emi_schedules, [("due_date", ASCENDING)])
    await _safe_create_index(db.emi_schedules, [("status", ASCENDING)])

    # EMI Escalations
    await _safe_create_index(db.emi_escalations, [("loan_id", ASCENDING)])
    await _safe_create_index(db.emi_escalations, [("customer_id", ASCENDING)])
    await _safe_create_index(db.emi_escalations, [("status", ASCENDING)])

    # Notifications
    await _safe_create_index(db.customer_notifications, [("customer_id", ASCENDING)])
    await _safe_create_index(db.customer_notifications, [("created_at", ASCENDING)])

    # Support
    await _safe_create_index(db.support_tickets, [("ticket_id", ASCENDING)], unique=True)

    # Payments
    await _safe_create_index(db.cashfree_payments, [("order_id", ASCENDING)], unique=True)

    # Idempotency
    await _safe_create_index(
        db.idempotency_requests,
        [("expires_at", ASCENDING)],
        expireAfterSeconds=0,
    )

    # Migration (safe)
    staff_roles = ["admin", "manager", "verification"]
    legacy_staff = await db.users.find({"role": {"$in": staff_roles}}).to_list(length=1000)

    for row in legacy_staff:
        email = row.get("email")
        if not email:
            continue

        await db.staff_users.update_one(
            {"email": email},
            {"$setOnInsert": row},
            upsert=True,
        )

        await db.users.delete_one({"_id": row.get("_id")})

    print("✅ Index initialization complete")


# ✅ CRITICAL FIX (YOU WERE MISSING THIS)
async def connect_db():
    print("🚀 Starting DB connection...")
    get_client()
    await init_indexes()


# ✅ CRITICAL FIX
async def close_db():
    global client
    if client:
        print("❌ Closing DB connection...")
        client.close()
        client = None