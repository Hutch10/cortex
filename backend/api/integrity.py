from fastapi import APIRouter, Body
from services.audit import pulse_audit
from services.export import export_service
from services.identity import identity_service
from datetime import datetime
import hashlib

router = APIRouter()

@router.get("/integrity/identity")
async def get_identity():
    return {
        "cortex_id": identity_service.get_public_id(),
        "status": "sealed",
        "standard": "FAA-P145-SOVEREIGN"
    }

@router.post("/integrity/seal")
async def create_seal(payload: str = Body(..., embed=True), 
                      metadata: dict = Body(..., embed=True)):
    # 1. Generate SHA-256 Hash
    data_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    
    # 2. Sign
    signature = identity_service.sign_payload(payload)
    
    entry = {
        "_id": metadata.get("timestamp", str(datetime.now())),
        "notes": payload,
        "kp_index": metadata.get("kp_index", 0),
        "seismic_count": metadata.get("seismic_count", 0),
        "fingerprint": data_hash,
        "integrity_seal": signature,
        "cortex_id": identity_service.get_public_id()
    }

    # 3. Mirror to Cortex Pulse Ledger
    pulse_audit.log_entry(entry)
    
    return entry

@router.get("/integrity/ledger")
async def get_ledger():
    return pulse_audit.get_all_entries()

@router.get("/integrity/export/obsidian")
async def export_obsidian():
    content = export_service.generate_obsidian_bundle()
    return {"content": content, "filename": f"terrapulse_brain_{datetime.now().strftime('%Y%m%d')}.md"}
