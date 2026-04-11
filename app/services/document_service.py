import os
from bson import ObjectId
from fastapi import HTTPException
from ..database.mongo import get_db
from ..core.config import settings

async def get_document_binary(document_id: str | ObjectId):
    """
    Retrieve document binary data. Supports both legacy MongoDB Binary 
    and new filesystem-based storage (UPLOAD_BASE_PATH).
    """
    db = await get_db()

    if isinstance(document_id, str):
        try:
            document_id = ObjectId(document_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid document ID format")

    doc = await db.documents.find_one({"_id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # ✅ SUPPORT DISK-BASED STORAGE (Phase 3.2)
    if "file_path" in doc:
        file_path = doc["file_path"]
        if os.path.exists(file_path):
            try:
                with open(file_path, "rb") as f:
                    doc["data"] = f.read()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to read file from disk: {str(e)}")
        else:
            # Fallback to Binary if path is broken but data is there (unlikely if migrated)
            if "data" not in doc:
                raise HTTPException(status_code=404, detail="Document file not found on disk")

    return doc
