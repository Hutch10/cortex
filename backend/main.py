from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from api.core_api import router as core_router

app = FastAPI(title="HutchStack Cortex API", version="0.9.0-beta.1")

# Enable CORS for the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include modules
app.include_router(core_router, prefix="/api/v1/core")

@app.get("/")
async def root():
    return {"message": "TerraPulse Resonance API is online", "status": "stable"}

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "terrapulse-backend"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
