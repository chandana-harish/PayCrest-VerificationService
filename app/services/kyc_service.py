from datetime import datetime, timedelta
import random

from bson import ObjectId
from fastapi import HTTPException

from ..database.mongo import get_db
from .audit_service import write_audit_log
from ..utils.serializers import normalize_doc


def _normalize_customer_id(cid):
    try:
        if isinstance(cid, str) and cid.isdigit():
            return int(cid)
    except Exception:
        pass
    return cid


def _normalize_pan(value) -> str:
    return str(value or "").strip().upper()


def _normalize_aadhaar(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())

def _mask_pan(value: str) -> str:
    pan = _normalize_pan(value)
    if len(pan) != 10:
        return "-" if not pan else pan
    return f"{pan[:2]}******{pan[-2:]}"


def _mask_aadhaar(value: str) -> str:
    aadhaar = _normalize_aadhaar(value)
    if len(aadhaar) < 4:
        return "-" if not aadhaar else aadhaar
    return f"XXXX-XXXX-{aadhaar[-4:]}"


def _sanitize_kyc_doc(doc: dict | None, *, include_sensitive: bool = False) -> dict | None:
    if not doc:
        return doc

    out = normalize_doc(doc)
    pan_raw = _normalize_pan(out.get("pan_number"))
    aadhaar_raw = _normalize_aadhaar(out.get("aadhaar_number") or out.get("aadhar_number"))

    if not out.get("pan_masked") and pan_raw:
        out["pan_masked"] = _mask_pan(pan_raw)
    if not out.get("aadhaar_masked") and aadhaar_raw:
        out["aadhaar_masked"] = _mask_aadhaar(aadhaar_raw)

    if include_sensitive:
        out["pan_number"] = pan_raw or None
        out["aadhaar_number"] = aadhaar_raw or None
        out.pop("aadhar_number", None)
    else:
        out.pop("pan_number", None)
        out.pop("aadhaar_number", None)
        out.pop("aadhar_number", None)
    out.pop("pan_hash", None)
    out.pop("aadhaar_hash", None)
    return out


def compute_scores(payload: dict) -> dict:
    employment_status = str(payload.get("employment_status") or "").strip().lower()
    employment_score = 25 if employment_status in {"employed", "self-employed"} else 10
    income = float(payload.get("monthly_income") or 0)
    income_score = 25 if income >= 80000 else (20 if income >= 50000 else (15 if income >= 30000 else 10))
    emi_months = int(payload.get("existing_emi_months") or 0)
    emi_score = 25 if emi_months == 0 else (15 if emi_months <= 12 else 10)
    exp_years = int(payload.get("years_of_experience") or 0)
    experience_score = 25 if exp_years >= 5 else (15 if exp_years >= 2 else 10)

    total_score = employment_score + income_score + emi_score + experience_score

    match total_score:
        case score if score > 90:
            cibil = random.randint(750, 850)
        case score if 80 <= score <= 90:
            cibil = random.randint(700, 749)
        case score if 70 <= score < 80:
            cibil = random.randint(650, 699)
        case score if 60 <= score < 70:
            cibil = random.randint(600, 649)
        case _:
            cibil = random.randint(300, 599)

    return {
        "employment_score": employment_score,
        "income_score": income_score,
        "emi_score": emi_score,
        "experience_score": experience_score,
        "total_score": total_score,
        "cibil_score": cibil,
        "loan_eligible": cibil > 650,
    }


async def submit_kyc(customer_id: str, payload: dict) -> dict:
    db = await get_db()
    customer_id = _normalize_customer_id(customer_id)
    existing = await db.kyc_details.find_one({"customer_id": customer_id})

    user = await db.users.find_one({"customer_id": customer_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    errors = {}

    def norm(v):
        return str(v).strip().lower() if v is not None else None

    pan_number = _normalize_pan(payload.get("pan_number"))
    aadhaar_number = _normalize_aadhaar(payload.get("aadhaar_number"))

    if payload.get("full_name") and norm(payload["full_name"]) != norm(user.get("full_name")):
        errors["full_name"] = "Full name does not match registration"

    if payload.get("dob"):
        dob = payload["dob"]
        dob = dob.isoformat() if hasattr(dob, "isoformat") else str(dob)
        if norm(dob) != norm(user.get("dob")):
            errors["dob"] = "Date of birth does not match registration"
        payload["dob"] = dob

    user_pan = _normalize_pan(user.get("pan_number"))
    if pan_number:
        pan_matches_user = bool(user_pan and user_pan == pan_number)
        if not pan_matches_user:
            errors["pan_number"] = "PAN number does not match registration"

    if pan_number:
        pan_exists = await db.users.find_one(
            {
                "customer_id": {"$ne": customer_id},
                "pan_number": pan_number,
            }
        )
        if pan_exists:
            errors["pan_number"] = "PAN number already registered with another user"

    if aadhaar_number:
        aadhaar_exists = await db.kyc_details.find_one(
            {
                "customer_id": {"$ne": customer_id},
                "$or": [
                    {"aadhaar_number": aadhaar_number},
                    {"aadhar_number": aadhaar_number},
                ],
            }
        )
        if aadhaar_exists:
            errors["aadhaar_number"] = "Aadhaar number already used by another customer"

    if errors:
        raise HTTPException(status_code=400, detail={"error": "KYC validation failed", "details": errors})

    safe_payload = dict(payload)
    if pan_number:
        safe_payload["pan_number"] = pan_number
        safe_payload["pan_last4"] = pan_number[-4:]
        safe_payload["pan_masked"] = _mask_pan(pan_number)
    if aadhaar_number:
        safe_payload["aadhaar_number"] = aadhaar_number
        safe_payload["aadhaar_last4"] = aadhaar_number[-4:]
        safe_payload["aadhaar_masked"] = _mask_aadhaar(aadhaar_number)
    if existing and not pan_number:
        for key in ("pan_number", "pan_last4", "pan_masked"):
            if existing.get(key) is not None:
                safe_payload[key] = existing.get(key)
    if existing and not aadhaar_number:
        for key in ("aadhaar_number", "aadhaar_last4", "aadhaar_masked"):
            if existing.get(key) is not None:
                safe_payload[key] = existing.get(key)

    doc = {
        **safe_payload,
        "customer_id": customer_id,
        "employment_score": None,
        "income_score": None,
        "emi_score": None,
        "experience_score": None,
        "total_score": None,
        "cibil_score": None,
        "loan_eligible": False,
        "kyc_status": "pending",
        "verified_by": None,
        "remarks": None,
        "submitted_at": datetime.utcnow(),
        "verified_at": None,
    }

    if existing:
        if existing.get("kyc_status") == "rejected":
            await db.kyc_details.update_one({"_id": existing["_id"]}, {"$set": doc})
            updated_doc = await db.kyc_details.find_one({"_id": existing["_id"]})
            await write_audit_log(
                action="kyc_resubmit",
                actor_role="customer",
                actor_id=customer_id,
                entity_type="kyc",
                entity_id=str(customer_id),
                details={},
            )
            return _sanitize_kyc_doc(updated_doc)

        update_payload = {**safe_payload, "updated_at": datetime.utcnow()}
        await db.kyc_details.update_one({"_id": existing["_id"]}, {"$set": update_payload})
        updated_doc = await db.kyc_details.find_one({"_id": existing["_id"]})
        await write_audit_log(
            action="kyc_update",
            actor_role="customer",
            actor_id=customer_id,
            entity_type="kyc",
            entity_id=str(customer_id),
            details={"status": str(existing.get("kyc_status") or "pending")},
        )
        return _sanitize_kyc_doc(updated_doc)

    await db.kyc_details.insert_one(doc)
    await write_audit_log(
        action="kyc_submit",
        actor_role="customer",
        actor_id=customer_id,
        entity_type="kyc",
        entity_id=str(customer_id),
        details={},
    )
    return _sanitize_kyc_doc(doc)


async def verify_kyc(customer_id: str, verifier_id: str, approve: bool, scores=None, remarks=None):
    db = await get_db()
    customer_id = _normalize_customer_id(customer_id)

    kyc = await db.kyc_details.find_one({"customer_id": customer_id})
    if not kyc:
        raise HTTPException(status_code=404, detail="KYC not found")

    score_data = dict(scores) if scores else compute_scores(kyc)
    if "total_score" not in score_data:
        score_data["total_score"] = int(
            score_data.get("employment_score", 0)
            + score_data.get("income_score", 0)
            + score_data.get("emi_score", 0)
            + score_data.get("experience_score", 0)
        )
    if "cibil_score" not in score_data:
        total = int(score_data.get("total_score") or 0)
        score_data["cibil_score"] = max(300, min(900, 300 + round(total * 6)))
    score_data["loan_eligible"] = int(score_data.get("cibil_score") or 0) >= 650

    await db.kyc_details.update_one(
        {"_id": kyc["_id"]},
        {
            "$set": {
                **score_data,
                "kyc_status": "approved" if approve else "rejected",
                "verified_by": verifier_id,
                "remarks": remarks,
                "verified_at": datetime.utcnow(),
            }
        },
    )

    await db.users.update_one({"customer_id": customer_id}, {"$set": {"is_kyc_verified": approve}})

    updated = await db.kyc_details.find_one({"customer_id": customer_id})
    await write_audit_log(
        action="kyc_verify",
        actor_role="verification",
        actor_id=verifier_id,
        entity_type="kyc",
        entity_id=str(customer_id),
        details={"approve": bool(approve), "remarks": remarks},
    )
    return _sanitize_kyc_doc(updated)


async def get_kyc_by_customer(customer_id: str, *, include_sensitive: bool = False):
    db = await get_db()
    customer_id = _normalize_customer_id(customer_id)
    kyc = await db.kyc_details.find_one({"customer_id": customer_id})
    if not kyc:
        raise HTTPException(status_code=404, detail="KYC not found")
    out = _sanitize_kyc_doc(kyc, include_sensitive=include_sensitive)
    if include_sensitive and out is not None:
        user = await db.users.find_one({"customer_id": customer_id}, {"pan_masked": 1, "pan_last4": 1, "pan_number": 1})
        pan_masked = str((user or {}).get("pan_masked") or "").strip()
        if pan_masked:
            out["pan_masked"] = pan_masked
        if not out.get("pan_number"):
            user_pan = _normalize_pan((user or {}).get("pan_number"))
            if user_pan:
                out["pan_number"] = user_pan
    return out


async def attach_kyc_document(customer_id: int, doc_type: str, document_id: str):
    db = await get_db()
    await db.kyc_details.update_one({"customer_id": customer_id}, {"$set": {doc_type: ObjectId(document_id)}})


async def get_verification_dashboard(page: int = 1, limit: int = 50):
    db = await get_db()
    try:
        page = int(page)
    except Exception:
        page = 1
    try:
        limit = int(limit)
    except Exception:
        limit = 50
    page = max(1, page)
    limit = max(1, min(limit, 200))
    skip = (page - 1) * limit

    pending_kyc_cursor = db.kyc_details.find({"kyc_status": "pending"}).sort("submitted_at", -1)
    pending_kyc = await pending_kyc_cursor.skip(skip).limit(limit).to_list(length=limit)
    pending_kyc_total = await db.kyc_details.count_documents({"kyc_status": "pending"})

    personal_cursor = db.personal_loans.find({"status": "assigned_to_verification"}).sort("applied_at", -1)
    vehicle_cursor = db.vehicle_loans.find({"status": "assigned_to_verification"}).sort("applied_at", -1)
    education_cursor = db.education_loans.find({"status": "assigned_to_verification"}).sort("applied_at", -1)
    home_cursor = db.home_loans.find({"status": "assigned_to_verification"}).sort("applied_at", -1)
    pending_personal = await personal_cursor.skip(skip).limit(limit).to_list(length=limit)
    pending_vehicle = await vehicle_cursor.skip(skip).limit(limit).to_list(length=limit)
    pending_education = await education_cursor.skip(skip).limit(limit).to_list(length=limit)
    pending_home = await home_cursor.skip(skip).limit(limit).to_list(length=limit)
    pending_personal_total = await db.personal_loans.count_documents({"status": "assigned_to_verification"})
    pending_vehicle_total = await db.vehicle_loans.count_documents({"status": "assigned_to_verification"})
    pending_education_total = await db.education_loans.count_documents({"status": "assigned_to_verification"})
    pending_home_total = await db.home_loans.count_documents({"status": "assigned_to_verification"})

    cutoff = datetime.utcnow() - timedelta(days=30)
    processed_kyc_cursor = db.kyc_details.find({"verified_at": {"$gte": cutoff}}).sort("verified_at", -1)
    processed_kyc = await processed_kyc_cursor.skip(skip).limit(limit).to_list(length=limit)
    processed_kyc_total = await db.kyc_details.count_documents({"verified_at": {"$gte": cutoff}})

    processed_personal_cursor = db.personal_loans.find(
        {"status": {"$in": ["verification_done", "rejected"]}, "verification_completed_at": {"$gte": cutoff}}
    ).sort("verification_completed_at", -1)
    processed_vehicle_cursor = db.vehicle_loans.find(
        {"status": {"$in": ["verification_done", "rejected"]}, "verification_completed_at": {"$gte": cutoff}}
    ).sort("verification_completed_at", -1)
    processed_education_cursor = db.education_loans.find(
        {"status": {"$in": ["verification_done", "rejected"]}, "verification_completed_at": {"$gte": cutoff}}
    ).sort("verification_completed_at", -1)
    processed_home_cursor = db.home_loans.find(
        {"status": {"$in": ["verification_done", "rejected"]}, "verification_completed_at": {"$gte": cutoff}}
    ).sort("verification_completed_at", -1)
    processed_personal = await processed_personal_cursor.skip(skip).limit(limit).to_list(length=limit)
    processed_vehicle = await processed_vehicle_cursor.skip(skip).limit(limit).to_list(length=limit)
    processed_education = await processed_education_cursor.skip(skip).limit(limit).to_list(length=limit)
    processed_home = await processed_home_cursor.skip(skip).limit(limit).to_list(length=limit)
    processed_personal_total = await db.personal_loans.count_documents(
        {"status": {"$in": ["verification_done", "rejected"]}, "verification_completed_at": {"$gte": cutoff}}
    )
    processed_vehicle_total = await db.vehicle_loans.count_documents(
        {"status": {"$in": ["verification_done", "rejected"]}, "verification_completed_at": {"$gte": cutoff}}
    )
    processed_education_total = await db.education_loans.count_documents(
        {"status": {"$in": ["verification_done", "rejected"]}, "verification_completed_at": {"$gte": cutoff}}
    )
    processed_home_total = await db.home_loans.count_documents(
        {"status": {"$in": ["verification_done", "rejected"]}, "verification_completed_at": {"$gte": cutoff}}
    )

    combined_processed_loans = [normalize_doc(l) for l in (processed_personal + processed_vehicle + processed_education + processed_home)]

    return {
        "pending_kyc": [_sanitize_kyc_doc(k, include_sensitive=True) for k in pending_kyc],
        "pending_kyc_total": int(pending_kyc_total),
        "pending_personal_loans": [normalize_doc(l) for l in pending_personal],
        "pending_vehicle_loans": [normalize_doc(l) for l in pending_vehicle],
        "pending_education_loans": [normalize_doc(l) for l in pending_education],
        "pending_home_loans": [normalize_doc(l) for l in pending_home],
        "pending_personal_total": int(pending_personal_total),
        "pending_vehicle_total": int(pending_vehicle_total),
        "pending_education_total": int(pending_education_total),
        "pending_home_total": int(pending_home_total),
        "processed_kyc": [_sanitize_kyc_doc(k, include_sensitive=True) for k in processed_kyc],
        "processed_kyc_total": int(processed_kyc_total),
        "processed_personal_loans": [normalize_doc(l) for l in processed_personal],
        "processed_vehicle_loans": [normalize_doc(l) for l in processed_vehicle],
        "processed_education_loans": [normalize_doc(l) for l in processed_education],
        "processed_home_loans": [normalize_doc(l) for l in processed_home],
        "processed_personal_total": int(processed_personal_total),
        "processed_vehicle_total": int(processed_vehicle_total),
        "processed_education_total": int(processed_education_total),
        "processed_home_total": int(processed_home_total),
        "processed_loan_verifications": combined_processed_loans,
        "page": page,
        "page_size": limit,
    }
