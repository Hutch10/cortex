import httpx
from datetime import datetime
from typing import List, Dict, Any

class NOAAService:
    BASE_URL = "https://services.swpc.noaa.gov/json"
    
    async def get_planetary_k_index(self) -> List[Dict[str, Any]]:
        """Fetch the most recent planetary k-index (Kp)."""
        url = f"{self.BASE_URL}/planetary_k_index_1m.json"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def get_latest_kp(self) -> float:
        """Helper to get the most recent Kp value."""
        data = await self.get_planetary_k_index()
        if not data:
            return 0.0
        # The data is usually sorted by time, get the last one
        return float(data[-1].get("kp_index", 0.0))

    async def get_solar_flares(self) -> List[Dict[str, Any]]:
        """Fetch recent solar flare activity (X-ray flux)."""
        # Generic placeholder for real-time flare JSON if needed
        # Often planetary_k_index is a good proxy for general resonance
        return []

noaa_service = NOAAService()
