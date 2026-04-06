"""
api/routes/cells.py — 细胞类型接口
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas import CellTypeItem, CellTypeListResponse
from database.models import CellType, CellSubtype, CellMarkerEntry

router = APIRouter(prefix="/api/cell-types", tags=["cell-types"])


@router.get("", response_model=CellTypeListResponse)
def list_cell_types(db: Session = Depends(get_db)):
    """获取所有细胞类型，附带 Marker 计数和亚型列表。"""

    rows = (
        db.query(
            CellType.name,
            func.count(distinct(CellMarkerEntry.marker_id)).label("marker_count"),
            func.count(CellMarkerEntry.id).label("entry_count"),
        )
        .outerjoin(CellMarkerEntry, CellType.id == CellMarkerEntry.cell_type_id)
        .group_by(CellType.id, CellType.name)
        .order_by(func.count(CellMarkerEntry.id).desc())
        .all()
    )

    results = []
    for r in rows:
        subtypes = [
            s.name for s in
            db.query(CellSubtype.name)
            .join(CellType, CellSubtype.cell_type_id == CellType.id)
            .filter(CellType.name == r.name)
            .distinct()
            .all()
        ]
        results.append(
            CellTypeItem(
                name=r.name,
                marker_count=r.marker_count,
                entry_count=r.entry_count,
                subtypes=sorted(subtypes),
            )
        )

    return CellTypeListResponse(total=len(results), results=results)
