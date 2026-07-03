import httpx
from typing import List, Dict, Any

class USGSService:
    BASE_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary"
    
    async def get_recent_tremors(self, magnitude: float = 1.0) -> Dict[str, Any]:
        """Fetch significant tremors from the last hour."""
        url = f"{self.BASE_URL}/all_hour.geojson"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            
            # Filter by magnitude if necessary
            features = data.get("features", [])
            filtered = [f for f in features if f["properties"]["mag"] >= magnitude]
            return {"count": len(filtered), "features": filtered}

usgs_service = USGSService()
