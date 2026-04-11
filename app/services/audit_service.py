from __future__ import annotations
from datetime import datetime
from typing import Any
from ..database.mongo import get_db


async def write_audit_log(
    *,
    action: str,
    actor_role: str | None = None,
    actor_id: str | int | None = None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    details: dict | None = None,
):
    try:
        db = await get_db()
        await db.audit_logs.insert_one({
            "action": action,
            "actor_role": actor_role,
            "actor_id": str(actor_id) if actor_id is not None else None,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "details": details or {},
            "created_at": datetime.utcnow(),
        })
    except Exception:
        return