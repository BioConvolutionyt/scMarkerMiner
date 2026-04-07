"""
api/routes/markers.py — Marker 检索、排行、详情接口
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, distinct, text
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

def do_search(
    db: Session,
    cell_type=None, cell_subtype=None, marker=None,
    tissue=None, disease=None, page=1, page_size=20,
    total_hint: int = 0,
) -> MarkerSearchResponse:
    """Core search logic, usable from both the route and the init endpoint.
    When total_hint > 0 the expensive count query is skipped (pagination reuse).
    """

    def _apply_filters(q):
        if cell_type:
            q = q.filter(CellType.name.in_(cell_type))
        if cell_subtype:
            q = q.join(CellSubtype, CellMarkerEntry.cell_subtype_id == CellSubtype.id).filter(
                CellSubtype.name.in_(cell_subtype)
            )
        if marker:
            q = q.filter(Marker.symbol.ilike(f"%{marker}%"))
        if tissue:
            q = q.join(Tissue, CellMarkerEntry.tissue_id == Tissue.id).filter(
                Tissue.name.in_(tissue)
            )
        if disease:
            q = q.join(Disease, CellMarkerEntry.disease_id == Disease.id).filter(
                Disease.name.in_(disease)
            )
        return q

    if total_hint > 0:
        total = total_hint
    else:
        count_q = (
            db.query(func.count(CellMarkerEntry.id))
            .join(Marker, CellMarkerEntry.marker_id == Marker.id)
            .join(CellType, CellMarkerEntry.cell_type_id == CellType.id)
        )
        total = _apply_filters(count_q).scalar()

    data_q = (
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
    )

    if cell_type:
        data_q = data_q.filter(CellType.name.in_(cell_type))
    if cell_subtype:
        data_q = data_q.filter(CellSubtype.name.in_(cell_subtype))
    if marker:
        data_q = data_q.filter(Marker.symbol.ilike(f"%{marker}%"))
    if tissue:
        data_q = data_q.filter(Tissue.name.in_(tissue))
    if disease:
        data_q = data_q.filter(Disease.name.in_(disease))

    rows = (
        data_q.order_by(Marker.citation_count.desc(), Marker.symbol, CellType.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return MarkerSearchResponse(
        total=total, page=page, page_size=page_size,
        results=[
            MarkerEntryItem(
                marker=r.symbol, cell_type=r.cell_type,
                cell_subtype=r.cell_subtype, tissue=r.tissue,
                disease=r.disease, pmid=r.pmid,
                pmcid=r.pmcid, marker_status=r.marker_status,
            )
            for r in rows
        ],
    )


@router.get("/search", response_model=MarkerSearchResponse)
def search_markers(
    cell_type: Optional[list[str]] = Query(None, description="细胞类型（多选）"),
    cell_subtype: Optional[list[str]] = Query(None, description="细胞亚型（多选）"),
    marker: Optional[str] = Query(None, description="Marker 基因符号（模糊）"),
    tissue: Optional[list[str]] = Query(None, description="组织类型（多选）"),
    disease: Optional[list[str]] = Query(None, description="疾病类型（多选）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(API_PAGE_SIZE, ge=1, le=API_MAX_PAGE_SIZE),
    total_hint: int = Query(0, ge=0, description="已知总数，> 0 时跳过 count 查询"),
    db: Session = Depends(get_db),
):
    return do_search(db, cell_type, cell_subtype, marker, tissue, disease,
                     page, page_size, total_hint=total_hint)


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
    page: int = Query(1, ge=1),
    page_size: int = Query(API_PAGE_SIZE, ge=1, le=API_MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    marker_obj = db.query(Marker).filter(Marker.symbol == symbol).first()
    if not marker_obj:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Marker '{symbol}' not found")

    agg = _get_marker_aggregates(db, symbol)

    total_entries = (
        db.query(func.count(CellMarkerEntry.id))
        .filter(CellMarkerEntry.marker_id == marker_obj.id)
        .scalar()
    )

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
        .order_by(CellType.name, Paper.pmcid)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return MarkerDetailResponse(
        symbol=symbol,
        citation_count=agg["citation_count"],
        cell_types=agg["cell_types"],
        subtypes=agg["subtypes"],
        tissues=agg["tissues"],
        diseases=agg["diseases"],
        total_entries=total_entries,
        page=page,
        page_size=page_size,
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
    """获取单个 Marker 的聚合信息，使用 1 条 SQL + GROUP_CONCAT 完成。"""
    row = db.execute(text(
        "SELECT m.citation_count, "
        "  GROUP_CONCAT(DISTINCT ct.name ORDER BY ct.name SEPARATOR '||') AS cell_types, "
        "  GROUP_CONCAT(DISTINCT cs.name ORDER BY cs.name SEPARATOR '||') AS subtypes, "
        "  GROUP_CONCAT(DISTINCT t.name ORDER BY t.name SEPARATOR '||') AS tissues, "
        "  GROUP_CONCAT(DISTINCT d.name ORDER BY d.name SEPARATOR '||') AS diseases "
        "FROM cell_marker_entries e "
        "JOIN markers m ON e.marker_id = m.id "
        "JOIN cell_types ct ON e.cell_type_id = ct.id "
        "LEFT JOIN cell_subtypes cs ON e.cell_subtype_id = cs.id "
        "LEFT JOIN tissues t ON e.tissue_id = t.id "
        "LEFT JOIN diseases d ON e.disease_id = d.id "
        "WHERE m.symbol = :sym "
        "GROUP BY m.id"
    ), {"sym": symbol}).first()

    if not row:
        return {"citation_count": 0, "cell_types": [], "subtypes": [], "tissues": [], "diseases": []}

    def _split(val):
        return sorted(val.split("||")) if val else []

    return {
        "citation_count": row.citation_count or 0,
        "cell_types": _split(row.cell_types),
        "subtypes": _split(row.subtypes),
        "tissues": _split(row.tissues),
        "diseases": _split(row.diseases),
    }
