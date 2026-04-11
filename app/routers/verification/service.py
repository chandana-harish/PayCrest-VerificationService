"""
services/verification-service/app/routers/verification/service.py
"""
from ...database.mongo import get_db
from ...services.kyc_service import get_verification_dashboard, verify_kyc, get_kyc_by_customer
from ...services.document_service import get_document_binary
from ...core.config import settings
import httpx
from fastapi import HTTPException


async def verification_complete(
    loan_collection: str,
    loan_id: str,
    approved: bool,
    verifier_id,
) -> dict:
    """
    Calls loan-service internal endpoint directly (not via gateway).
    URL: http://localhost:3002/internal/verification-complete
    """
    # Call loan-service directly — no /api/loans prefix since this bypasses gateway
    url = f"{settings.LOAN_SERVICE_URL}/internal/verification-complete"
    payload = {
        "loan_collection": loan_collection,
        "loan_id": str(loan_id),
        "approved": approved,
        "verifier_id": str(verifier_id),
    }
    headers = {
        "X-Internal-Token": settings.INTERNAL_SERVICE_TOKEN,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                return response.json()
            raise HTTPException(
                status_code=response.status_code,
                detail=f"loan-service verification error: {response.text}",
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="loan-service is unavailable")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="loan-service timed out")


__all__ = [
    "get_db",
    "get_verification_dashboard",
    "verify_kyc",
    "get_kyc_by_customer",
    "verification_complete",
    "get_document_binary",
]