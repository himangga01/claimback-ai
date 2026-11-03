import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.routes import router

app = FastAPI(
    title="ClaimBack-AI Backend API",
    description="Meta Global AI Developer Hackathon: Pro Se Visual Evidence Forensics & Dual-Court Auto-Packager",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://himangga01.github.io"],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "healthy"}


# 프론트엔드 정적 파일 마운트 (루트 진입 시 3분할 데모 대시보드 자동 서빙)
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
