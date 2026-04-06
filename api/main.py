"""
api/main.py — FastAPI 应用入口

开发模式：uvicorn api.main:app --reload
生产模式：FastAPI 同时托管前端静态文件 (frontend/dist)
API 文档：http://localhost:8000/docs
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import API_CORS_ORIGINS, API_HOST, API_PORT
from database.models import init_db

from api.routes import markers, cells, stats, export

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
IS_VERCEL = os.getenv("VERCEL") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not IS_VERCEL:
        init_db()
    yield


app = FastAPI(
    title="scMarkerMiner Database API",
    description="单细胞 Marker 数据库 — 多维检索、可信度排行、可视化、数据导出",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=API_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(markers.router)
app.include_router(cells.router)
app.include_router(stats.router)
app.include_router(export.router)


@app.get("/api", tags=["root"])
def api_root():
    return {
        "name": "scMarkerMiner Database API",
        "version": "0.1.0",
        "docs": "/docs",
    }


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(request: Request, full_path: str):
        """Vue Router 使用 history 模式，所有非 API 路径回退到 index.html。"""
        file = FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host=API_HOST, port=API_PORT, reload=True)
