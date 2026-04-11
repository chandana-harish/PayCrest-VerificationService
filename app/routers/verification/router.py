from fastapi import APIRouter, Depends , HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from ...core.security import require_roles
from ...models.enums import Roles, LoanCollection, DocumentType
from .service import get_db
from .service import get_verification_dashboard, verify_kyc, get_kyc_by_customer, verification_complete, get_document_binary
from ...schemas.kyc import KYCOut, KYCVerify
from bson import ObjectId
import io
router = APIRouter(prefix="", tags=["verification"])

@router.get('/dashboard')
async def dashboard(user=Depends(require_roles(Roles.VERIFICATION))):
    return await get_verification_dashboard()

@router.put('/verify-kyc/{customer_id}', response_model=KYCOut)
async def verify_kyc_route(customer_id: str, payload: KYCVerify, user=Depends(require_roles(Roles.VERIFICATION))):
    scores = {
        "employment_score": int(payload.employment_score),
        "income_score": int(payload.income_score),
        "emi_score": int(payload.emi_score),
        "experience_score": int(payload.experience_score),
    }
    if payload.total_score is not None:
        scores["total_score"] = int(payload.total_score)
    if payload.cibil_score is not None:
        scores["cibil_score"] = int(payload.cibil_score)
    return await verify_kyc(customer_id, user['_id'], payload.approve, scores, payload.remarks)


@router.get('/kyc/{customer_id}', response_model=KYCOut)
async def get_kyc_route(customer_id: str, user=Depends(require_roles(Roles.VERIFICATION))):
    return await get_kyc_by_customer(customer_id, include_sensitive=True)

@router.put('/verify-loan/{loan_collection}/{loan_id}')
async def verify_loan_route(loan_collection: LoanCollection, loan_id: str, approved: bool, user=Depends(require_roles(Roles.VERIFICATION))):
    return await verification_complete(loan_collection.value, loan_id, approved, user["_id"])


@router.get('/kyc-documents/{customer_id}')
async def get_kyc_documents(customer_id: str, user=Depends(require_roles(Roles.VERIFICATION))):
    """Get list of uploaded KYC documents for a customer."""
    db = await get_db()

    kyc = await db.kyc_details.find_one({"customer_id": int(customer_id)})
    if not kyc:
        return {"error": "KYC not found"}

    return {
        "customer_id": customer_id,
        "pan_card": str(kyc.get("pan_card")) if kyc.get("pan_card") else None,
        "aadhar_card": str(kyc.get("aadhar_card")) if kyc.get("aadhar_card") else None,
        "photo": str(kyc.get("photo")) if kyc.get("photo") else None,
    }

@router.get('/download-kyc-document/{customer_id}/{doc_type}')
async def download_kyc_document(
    customer_id: str,
    doc_type: DocumentType,
    user=Depends(require_roles(Roles.VERIFICATION))
):
    db = await get_db()
    kyc = await db.kyc_details.find_one({"customer_id": int(customer_id)})
    if not kyc:
        raise HTTPException(404, "KYC not found")

    doc_id = kyc.get(doc_type.value)
    if not doc_id:
        raise HTTPException(404, "Document not found")

    doc = await get_document_binary(str(doc_id))

    return StreamingResponse(
        io.BytesIO(doc["data"]),
        media_type=doc["content_type"],
        headers={
            "Content-Disposition": f'inline; filename="{doc["filename"]}"'
        }
    )


@router.get('/loan-documents/{loan_id}')
async def get_loan_documents(loan_id: str, user=Depends(require_roles(Roles.VERIFICATION))):
    """Get list of uploaded loan documents."""
    db = await get_db()
    # Try both personal and vehicle loans
    loan = await db.personal_loans.find_one({"loan_id": int(loan_id)})
    if not loan:
        loan = await db.vehicle_loans.find_one({"loan_id": int(loan_id)})
    if not loan:
        loan = await db.education_loans.find_one({"loan_id": int(loan_id)})
    if not loan:
        loan = await db.home_loans.find_one({"loan_id": int(loan_id)})
    
    if not loan:
        return {"error": "Loan not found"}
    
    return {
    "loan_id": loan_id,
    "pay_slip": str(loan.get("pay_slip")) if loan.get("pay_slip") else None,
    "vehicle_price_doc": str(loan.get("vehicle_price_doc")) if loan.get("vehicle_price_doc") else None,
    "home_property_doc": str(loan.get("home_property_doc")) if loan.get("home_property_doc") else None,
    "fees_structure": str(loan.get("fees_structure")) if loan.get("fees_structure") else None,
    "bonafide_certificate": str(loan.get("bonafide_certificate")) if loan.get("bonafide_certificate") else None,
    "collateral_doc": str(loan.get("collateral_doc")) if loan.get("collateral_doc") else None,
}


@router.get('/download-loan-document/{loan_id}/{doc_type}')
async def download_loan_document(
    loan_id: str,
    doc_type: DocumentType,
    user=Depends(require_roles(Roles.VERIFICATION))
):
    db = await get_db()

    loan = await db.personal_loans.find_one({"loan_id": int(loan_id)})
    if not loan:
        loan = await db.vehicle_loans.find_one({"loan_id": int(loan_id)})
    if not loan:
        loan = await db.education_loans.find_one({"loan_id": int(loan_id)})
    if not loan:
        loan = await db.home_loans.find_one({"loan_id": int(loan_id)})

    if not loan:
        raise HTTPException(404, "Loan not found")

    doc_id = loan.get(doc_type.value)
    if not doc_id:
        raise HTTPException(404, "Document not found")

    doc = await get_document_binary(str(doc_id))

    return StreamingResponse(
        io.BytesIO(doc["data"]),
        media_type=doc["content_type"],
        headers={
            "Content-Disposition": f'inline; filename="{doc["filename"]}"'
        }
    )




