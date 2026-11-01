from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router

app = FastAPI(
    title="ClaimBack-AI Backend API",
    description="Meta Global AI Developer Hackathon: Pro Se Visual Evidence Forensics & Dual-Court Auto-Packager",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {
        "project": "ClaimBack-AI",
        "description": "Pro Se Dual-Court Visual Evidence Forensics & Document Packaging Pipeline",
        "status": "online",
        "supported_jurisdictions": ["KR (대한민국 법원 전자소송 / 우체국 전자내용증명)", "US (California Small Claims Form SC-100)"],
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
