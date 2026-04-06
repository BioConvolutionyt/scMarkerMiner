"""
api/routes/markers.py — Marker 检索、排行、详情接口
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas import (
    MarkerEntryItem,
    MarkerSearchResponse,
    MarkerRankingItem,
    MarkerRankingResponse,
    MarkerDetailResponse,
)
from config.settings import API_PAGE_SIZE, API_MAX_PAGE_SIZE
from database.models import (
    CellMarkerEntry,
    CellType,
    CellSubtype,
    Marker,
    Tissue,
    Disease,
    Paper,
)

router = APIRouter(prefix="/api/markers", tags=["markers"])


# =====================================================================
# GET /api/markers/search — 多维检索
# =====================================================================

@router.get("/search", response_model=MarkerSearchResponse)
def search_markers(
    cell_type: Optional[list[str]] = Query(None, description="细胞类型（多选）"),
    cell_subtype: Optional[list[str]] = Query(None, description="细胞亚型（多选）"),
    marker: Optional[str] = Query(None, description="Marker 基因符号（模糊）"),
    tissue: Optional[list[str]] = Query(None, description="组织类型（多选）"),
    disease: Optional[list[str]] = Query(None, description="疾病类型（多选）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(API_PAGE_SIZE, ge=1, le=API_MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    cite_sq = (
        db.query(
            CellMarkerEntry.marker_id,
            func.count(distinct(CellMarkerEntry.paper_id)).label("cite_count"),
        )
        .group_by(CellMarkerEntry.marker_id)
        .subquery()
    )

    query = (
        db.query(
            Marker.symbol,
            CellType.name.label("cell_type"),
            CellSubtype.name.label("cell_subtype"),
            Tissue.name.label("tissue"),
            Disease.name.label("disease"),
            Paper.pmid,
            Paper.pmcid,
            CellMarkerEntry.marker_status,
        )
        .join(CellMarkerEntry, Marker.id == CellMarkerEntry.marker_id)
        .join(CellType, CellMarkerEntry.cell_type_id == CellType.id)
        .outerjoin(CellSubtype, CellMarkerEntry.cell_subtype_id == CellSubtype.id)
        .outerjoin(Tissue, CellMarkerEntry.tissue_id == Tissue.id)
        .outerjoin(Disease, CellMarkerEntry.disease_id == Disease.id)
        .join(Paper, CellMarkerEntry.paper_id == Paper.id)
        .outerjoin(cite_sq, Marker.id == cite_sq.c.marker_id)
    )

    if cell_type:
        query = query.filter(CellType.name.in_(cell_type))
    if cell_subtype:
        query = query.filter(CellSubtype.name.in_(cell_subtype))
    if marker:
        query = query.filter(Marker.symbol.ilike(f"%{marker}%"))
    if tissue:
        query = query.filter(Tissue.name.in_(tissue))
    if disease:
        query = query.filter(Disease.name.in_(disease))

    total = query.count()
    rows = (
        query.order_by(cite_sq.c.cite_count.desc(), Marker.symbol, CellType.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    results = [
        MarkerEntryItem(
            marker=r.symbol,
            cell_type=r.cell_type,
            cell_subtype=r.cell_subtype,
            tissue=r.tissue,
            disease=r.disease,
            pmid=r.pmid,
            pmcid=r.pmcid,
            marker_status=r.marker_status,
        )
        for r in rows
    ]

    return MarkerSearchResponse(
        total=total, page=page, page_size=page_size, results=results
    )


# =====================================================================
# GET /api/markers/ranking — 可信度排行
# =====================================================================

@router.get("/ranking", response_model=MarkerRankingResponse)
def marker_ranking(
    limit: int = Query(50, ge=1, le=500),
    cell_type: Optional[str] = Query(None),
    tissue: Optional[str] = Query(None),
    disease: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = (
        db.query(
            Marker.symbol,
            func.count(distinct(CellMarkerEntry.paper_id)).label("citation_count"),
            func.count(distinct(CellMarkerEntry.cell_type_id)).label("cell_type_count"),
        )
        .join(CellMarkerEntry, Marker.id == CellMarkerEntry.marker_id)
        .join(CellType, CellMarkerEntry.cell_type_id == CellType.id)
        .outerjoin(Tissue, CellMarkerEntry.tissue_id == Tissue.id)
        .outerjoin(Disease, CellMarkerEntry.disease_id == Disease.id)
    )

    if cell_type:
        query = query.filter(CellType.name.ilike(f"%{cell_type}%"))
    if tissue:
        query = query.filter(Tissue.name.ilike(f"%{tissue}%"))
    if disease:
        query = query.filter(Disease.name.ilike(f"%{disease}%"))

    rows = (
        query.group_by(Marker.id, Marker.symbol)
        .order_by(func.count(distinct(CellMarkerEntry.paper_id)).desc())
        .limit(limit)
        .all()
    )

    results = []
    for r in rows:
        detail = _get_marker_aggregates(db, r.symbol)
        results.append(
            MarkerRankingItem(
                symbol=r.symbol,
                citation_count=r.citation_count,
                cell_type_count=r.cell_type_count,
                cell_types=detail["cell_types"],
                tissues=detail["tissues"],
                diseases=detail["diseases"],
            )
        )

    return MarkerRankingResponse(total=len(results), results=results)


# =====================================================================
# GET /api/markers/{symbol} — 单个 Marker 详情
# =====================================================================

@router.get("/{symbol}", response_model=MarkerDetailResponse)
def marker_detail(
    symbol: str,
    db: Session = Depends(get_db),
):
    marker_obj = db.query(Marker).filter(Marker.symbol == symbol).first()
    if not marker_obj:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Marker '{symbol}' not found")

    agg = _get_marker_aggregates(db, symbol)

    entries_q = (
        db.query(
            Marker.symbol,
            CellType.name.label("cell_type"),
            CellSubtype.name.label("cell_subtype"),
            Tissue.name.label("tissue"),
            Disease.name.label("disease"),
            Paper.pmid,
            Paper.pmcid,
            CellMarkerEntry.marker_status,
        )
        .join(CellMarkerEntry, Marker.id == CellMarkerEntry.marker_id)
        .join(CellType, CellMarkerEntry.cell_type_id == CellType.id)
        .outerjoin(CellSubtype, CellMarkerEntry.cell_subtype_id == CellSubtype.id)
        .outerjoin(Tissue, CellMarkerEntry.tissue_id == Tissue.id)
        .outerjoin(Disease, CellMarkerEntry.disease_id == Disease.id)
        .join(Paper, CellMarkerEntry.paper_id == Paper.id)
        .filter(Marker.symbol == symbol)
        .all()
    )

    return MarkerDetailResponse(
        symbol=symbol,
        citation_count=agg["citation_count"],
        cell_types=agg["cell_types"],
        subtypes=agg["subtypes"],
        tissues=agg["tissues"],
        diseases=agg["diseases"],
        entries=[
            MarkerEntryItem(
                marker=e.symbol,
                cell_type=e.cell_type,
                cell_subtype=e.cell_subtype,
                tissue=e.tissue,
                disease=e.disease,
                pmid=e.pmid,
                pmcid=e.pmcid,
                marker_status=e.marker_status,
            )
            for e in entries_q
        ],
    )


# =====================================================================
# Helpers
# =====================================================================

def _get_marker_aggregates(db: Session, symbol: str) -> dict:
    """获取单个 Marker 的聚合信息（关联的细胞类型、组织、疾病列表）。"""
    base = (
        db.query(CellMarkerEntry)
        .join(Marker, CellMarkerEntry.marker_id == Marker.id)
        .filter(Marker.symbol == symbol)
    )

    citation_count = base.with_entities(
        func.count(distinct(CellMarkerEntry.paper_id))
    ).scalar()

    cell_types = [
        r[0] for r in
        base.join(CellType, CellMarkerEntry.cell_type_id == CellType.id)
        .with_entities(distinct(CellType.name))
        .all()
    ]

    subtypes = [
        r[0] for r in
        base.join(CellSubtype, CellMarkerEntry.cell_subtype_id == CellSubtype.id)
        .with_entities(distinct(CellSubtype.name))
        .all()
        if r[0]
    ]

    tissues = [
        r[0] for r in
        base.join(Tissue, CellMarkerEntry.tissue_id == Tissue.id)
        .with_entities(distinct(Tissue.name))
        .all()
        if r[0]
    ]

    diseases = [
        r[0] for r in
        base.join(Disease, CellMarkerEntry.disease_id == Disease.id)
        .with_entities(distinct(Disease.name))
        .all()
        if r[0]
    ]

    return {
        "citation_count": citation_count or 0,
        "cell_types": sorted(cell_types),
        "subtypes": sorted(subtypes),
        "tissues": sorted(tissues),
        "diseases": sorted(diseases),
    }
