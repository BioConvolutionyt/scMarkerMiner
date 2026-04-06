"""
api/deps.py — FastAPI 依赖注入
"""

from sqlalchemy.orm import Session
from database.models import SessionLocal


def get_db():
    """提供数据库 Session，请求结束后自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
