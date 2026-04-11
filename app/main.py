from fastapi import FastAPI
from app.core.config import settings
from app.database.mongo import connect_db, close_db

from app.routers.verification.router import router as verification_router

from app.middleware.idempotency import IdempotencyMiddleware

app = FastAPI(title=settings.SERVICE_NAME + " API")
app.add_middleware(IdempotencyMiddleware)  # ✅ FIXED

app.include_router(verification_router)

@app.on_event("startup")
async def startup_db_client():
    await connect_db()

@app.on_event("shutdown")
async def shutdown_db_client():
    await close_db()

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": (settings.SERVICE_NAME or "verification-service"), "version": "1.0.0"}