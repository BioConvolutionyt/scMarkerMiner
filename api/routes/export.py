"""
api/routes/export.py — 数据导出接口（CSV / Excel）
"""

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from api.deps import get_db
from config.settings import EXPORT_MAX_ROWS
from database.models import (
    CellMarkerEntry,
    CellType,
    CellSubtype,
    Marker,
    Tissue,
    Disease,
    Paper,
)

router = APIRouter(prefix="/api/export", tags=["export"])

COLUMNS = [
    "marker", "cell_type", "cell_subtype",
    "tissue", "disease", "pmid", "pmcid", "marker_status",
]


def _build_export_query(
    db: Session,
    cell_type: Optional[list[str]],
    cell_subtype: Optional[list[str]],
    marker: Optional[str],
    tissue: Optional[list[str]],
    disease: Optional[list[str]],
):
    """构建与 marker search 相同逻辑的导出查询。"""
    query = (
        db.query(
            Marker.symbol.label("marker"),
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
        query = query.filter(CellType.name.in_(cell_type))
    if cell_subtype:
        query = query.filter(CellSubtype.name.in_(cell_subtype))
    if marker:
        query = query.filter(Marker.symbol.ilike(f"%{marker}%"))
    if tissue:
        query = query.filter(Tissue.name.in_(tissue))
    if disease:
        query = query.filter(Disease.name.in_(disease))

    return query.order_by(Marker.symbol).limit(EXPORT_MAX_ROWS)


# =====================================================================
# GET /api/export/csv
# =====================================================================

@router.get("/csv")
def export_csv(
    cell_type: Optional[list[str]] = Query(None),
    cell_subtype: Optional[list[str]] = Query(None),
    marker: Optional[str] = Query(None),
    tissue: Optional[list[str]] = Query(None),
    disease: Optional[list[str]] = Query(None),
    db: Session = Depends(get_db),
):
    rows = _build_export_query(db, cell_type, cell_subtype, marker, tissue, disease).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    for r in rows:
        writer.writerow([
            r.marker, r.cell_type, r.cell_subtype or "",
            r.tissue or "", r.disease or "",
            r.pmid or "", r.pmcid, r.marker_status or "",
        ])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cell_markers.csv"},
    )


# =====================================================================
# GET /api/export/xlsx
# =====================================================================

@router.get("/xlsx")
def export_xlsx(
    cell_type: Optional[list[str]] = Query(None),
    cell_subtype: Optional[list[str]] = Query(None),
    marker: Optional[str] = Query(None),
    tissue: Optional[list[str]] = Query(None),
    disease: Optional[list[str]] = Query(None),
    db: Session = Depends(get_db),
):
    from openpyxl import Workbook

    rows = _build_export_query(db, cell_type, cell_subtype, marker, tissue, disease).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Cell Markers"
    ws.append(COLUMNS)

    for r in rows:
        ws.append([
            r.marker, r.cell_type, r.cell_subtype or "",
            r.tissue or "", r.disease or "",
            r.pmid or "", r.pmcid, r.marker_status or "",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=cell_markers.xlsx"},
    )
