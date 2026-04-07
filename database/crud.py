"""
database/crud.py — 数据库 CRUD 操作

核心功能：get_or_create 模式（查找已有记录或创建新记录），
用于维度表（cell_types, markers, diseases, tissues）的去重写入。
"""

import logging
from typing import Optional

from sqlalchemy import func, distinct, text
from sqlalchemy.orm import Session

from database.models import (
    Paper,
    CellType,
    CellSubtype,
    Marker,
    Disease,
    Tissue,
    CellMarkerEntry,
)

logger = logging.getLogger(__name__)


def refresh_citation_counts(db: Session) -> int:
    """批量刷新 markers.citation_count = COUNT(DISTINCT paper_id)。"""
    db.execute(text(
        "UPDATE markers m "
        "JOIN ("
        "  SELECT marker_id, COUNT(DISTINCT paper_id) AS cnt "
        "  FROM cell_marker_entries GROUP BY marker_id"
        ") agg ON m.id = agg.marker_id "
        "SET m.citation_count = agg.cnt"
    ))
    db.commit()
    updated = db.query(Marker).filter(Marker.citation_count > 0).count()
    logger.info("Refreshed citation_count for %d markers", updated)
    return updated


# =====================================================================
# 通用 get_or_create
# =====================================================================

def get_or_create_paper(
    db: Session, pmcid: str, pmid: str = None,
    title: str = None, journal: str = None, pub_year: int = None,
) -> Paper:
    obj = db.query(Paper).filter(Paper.pmcid == pmcid).first()
    if obj:
        return obj
    obj = Paper(pmcid=pmcid, pmid=pmid, title=title, journal=journal, pub_year=pub_year)
    db.add(obj)
    db.flush()
    return obj


def get_or_create_cell_type(db: Session, name: str) -> CellType:
    obj = db.query(CellType).filter(CellType.name == name).first()
    if obj:
        return obj
    obj = CellType(name=name)
    db.add(obj)
    db.flush()
    return obj


def get_or_create_cell_subtype(
    db: Session, name: str, cell_type_id: int,
) -> CellSubtype:
    obj = (
        db.query(CellSubtype)
        .filter(CellSubtype.name == name, CellSubtype.cell_type_id == cell_type_id)
        .first()
    )
    if obj:
        return obj
    obj = CellSubtype(name=name, cell_type_id=cell_type_id)
    db.add(obj)
    db.flush()
    return obj


def get_or_create_marker(db: Session, symbol: str) -> Marker:
    obj = db.query(Marker).filter(Marker.symbol == symbol).first()
    if obj:
        return obj
    obj = Marker(symbol=symbol)
    db.add(obj)
    db.flush()
    return obj


def get_or_create_disease(db: Session, name: str) -> Disease:
    obj = db.query(Disease).filter(Disease.name == name).first()
    if obj:
        return obj
    obj = Disease(name=name)
    db.add(obj)
    db.flush()
    return obj


def get_or_create_tissue(db: Session, name: str) -> Tissue:
    obj = db.query(Tissue).filter(Tissue.name == name).first()
    if obj:
        return obj
    obj = Tissue(name=name)
    db.add(obj)
    db.flush()
    return obj


# =====================================================================
# 插入一条完整的 cell-marker 关联记录
# =====================================================================

def insert_cell_marker_entry(
    db: Session,
    paper_id: int,
    cell_type_name: str,
    marker_symbol: str,
    cell_subtype_name: Optional[str] = None,
    tissue_name: Optional[str] = None,
    disease_name: Optional[str] = None,
    marker_status: str = "approved",
) -> Optional[CellMarkerEntry]:
    """
    插入一条 cell-marker-paper 关联。自动处理维度表的 get_or_create。
    遇到完全重复的记录时跳过（返回 None）。
    """
    cell_type = get_or_create_cell_type(db, cell_type_name)

    cell_subtype = None
    if cell_subtype_name:
        cell_subtype = get_or_create_cell_subtype(db, cell_subtype_name, cell_type.id)

    marker = get_or_create_marker(db, marker_symbol)

    tissue = get_or_create_tissue(db, tissue_name) if tissue_name else None
    disease = get_or_create_disease(db, disease_name) if disease_name else None

    existing = (
        db.query(CellMarkerEntry)
        .filter(
            CellMarkerEntry.cell_type_id == cell_type.id,
            CellMarkerEntry.cell_subtype_id == (cell_subtype.id if cell_subtype else None),
            CellMarkerEntry.marker_id == marker.id,
            CellMarkerEntry.tissue_id == (tissue.id if tissue else None),
            CellMarkerEntry.disease_id == (disease.id if disease else None),
            CellMarkerEntry.paper_id == paper_id,
        )
        .first()
    )
    if existing:
        return None

    entry = CellMarkerEntry(
        cell_type_id=cell_type.id,
        cell_subtype_id=cell_subtype.id if cell_subtype else None,
        marker_id=marker.id,
        tissue_id=tissue.id if tissue else None,
        disease_id=disease.id if disease else None,
        paper_id=paper_id,
        marker_status=marker_status,
    )
    db.add(entry)
    db.flush()
    return entry
