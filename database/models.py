"""
database/models.py — SQLAlchemy ORM 模型

与 schema.sql 中的表结构一一对应，通过 ORM 进行 Python 层面的数据操作。
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Session,
    relationship,
    sessionmaker,
)

from config.settings import (
    SQLALCHEMY_DATABASE_URL,
    SQLALCHEMY_ECHO,
    SQLALCHEMY_POOL_SIZE,
)


# =====================================================================
# Base & Engine
# =====================================================================

class Base(DeclarativeBase):
    pass


engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=SQLALCHEMY_ECHO,
    pool_size=SQLALCHEMY_POOL_SIZE,
    pool_recycle=300,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Session:
    """获取数据库 Session（用于依赖注入或手动调用）。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """根据 ORM 模型创建全部表（如果不存在）。"""
    Base.metadata.create_all(bind=engine)


# =====================================================================
# ORM Models
# =====================================================================

class Paper(Base):
    __tablename__ = "papers"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    pmid       = Column(String(20), index=True)
    pmcid      = Column(String(20), nullable=False, unique=True)
    title      = Column(Text)
    journal    = Column(String(500))
    pub_year   = Column(Integer, index=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    entries = relationship("CellMarkerEntry", back_populates="paper")


class CellType(Base):
    __tablename__ = "cell_types"

    id   = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)

    subtypes = relationship("CellSubtype", back_populates="cell_type")
    entries  = relationship("CellMarkerEntry", back_populates="cell_type")


class CellSubtype(Base):
    __tablename__ = "cell_subtypes"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    name         = Column(String(255), nullable=False)
    cell_type_id = Column(Integer, ForeignKey("cell_types.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "cell_type_id", name="uniq_subtype"),
    )

    cell_type = relationship("CellType", back_populates="subtypes")
    entries   = relationship("CellMarkerEntry", back_populates="cell_subtype")


class Marker(Base):
    __tablename__ = "markers"

    id     = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(100), nullable=False, unique=True)
    name   = Column(String(500))

    entries = relationship("CellMarkerEntry", back_populates="marker")


class Disease(Base):
    __tablename__ = "diseases"

    id   = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False, unique=True)

    entries = relationship("CellMarkerEntry", back_populates="disease")


class Tissue(Base):
    __tablename__ = "tissues"

    id   = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)

    entries = relationship("CellMarkerEntry", back_populates="tissue")


class CellMarkerEntry(Base):
    __tablename__ = "cell_marker_entries"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    cell_type_id    = Column(Integer, ForeignKey("cell_types.id"), nullable=False)
    cell_subtype_id = Column(Integer, ForeignKey("cell_subtypes.id"))
    marker_id       = Column(Integer, ForeignKey("markers.id"), nullable=False)
    tissue_id       = Column(Integer, ForeignKey("tissues.id"))
    disease_id      = Column(Integer, ForeignKey("diseases.id"))
    paper_id        = Column(Integer, ForeignKey("papers.id"), nullable=False)
    marker_status   = Column(String(20), default="approved")
    created_at      = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "cell_type_id", "cell_subtype_id", "marker_id",
            "tissue_id", "disease_id", "paper_id",
            name="uniq_entry",
        ),
        Index("idx_marker", "marker_id"),
        Index("idx_cell", "cell_type_id"),
        Index("idx_disease", "disease_id"),
        Index("idx_tissue", "tissue_id"),
        Index("idx_paper", "paper_id"),
    )

    cell_type    = relationship("CellType",    back_populates="entries")
    cell_subtype = relationship("CellSubtype", back_populates="entries")
    marker       = relationship("Marker",      back_populates="entries")
    tissue       = relationship("Tissue",      back_populates="entries")
    disease      = relationship("Disease",     back_populates="entries")
    paper        = relationship("Paper",       back_populates="entries")
