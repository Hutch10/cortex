from fastapi import APIRouter
from services.noaa import noaa_service
from services.usgs import usgs_service
from services.surya_engine import surya_service
from datetime import datetime

router = APIRouter()

@router.get("/resonance/solar")
async def get_solar_resonance():
    kp = await noaa_service.get_latest_kp()
    return {"kp_index": kp, "status": "active", "timestamp": str(datetime.now())}

@router.get("/resonance/seismic")
async def get_seismic_resonance():
    tremors = await usgs_service.get_recent_tremors()
    return {"tremors": tremors, "status": "active"}

@router.get("/resonance/pulse")
async def get_combined_pulse():
    kp = await noaa_service.get_latest_kp()
    tremors = await usgs_service.get_recent_tremors()
    return {
        "solar": {"kp_index": kp},
        "seismic": {"count": tremors["count"]},
        "resonance_score": (kp * 0.7) + (tremors["count"] * 0.3)
    }

@router.get("/resonance/prediction")
async def get_surya_prediction():
    prediction = await surya_service.predict_resonance_window()
    return prediction
