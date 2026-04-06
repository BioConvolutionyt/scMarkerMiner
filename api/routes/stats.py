"""
api/routes/stats.py — 统计概览、筛选选项、可视化数据接口
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas import (
    OverviewStats,
    BubblePoint,
    FilterOptions,
    DistributionItem,
    DistributionData,
    DashboardData,
)
from database.models import (
    Paper,
    Marker,
    CellType,
    CellSubtype,
    Disease,
    Tissue,
    CellMarkerEntry,
)

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview", response_model=OverviewStats)
def overview(db: Session = Depends(get_db)):
    return _build_overview(db)


def _build_overview(db: Session) -> OverviewStats:
    return OverviewStats(
        total_papers=db.query(Paper).count(),
        total_markers=db.query(Marker).count(),
        total_cell_types=db.query(CellType).count(),
        total_diseases=db.query(Disease).count(),
        total_tissues=db.query(Tissue).count(),
        total_entries=db.query(CellMarkerEntry).count(),
    )


def _build_distribution(db: Session) -> DistributionData:
    cell_type_dist = (
        db.query(CellType.name, func.count(CellMarkerEntry.id).label("cnt"))
        .join(CellMarkerEntry, CellType.id == CellMarkerEntry.cell_type_id)
        .group_by(CellType.name)
        .order_by(func.count(CellMarkerEntry.id).desc())
        .limit(15)
        .all()
    )
    disease_dist = (
        db.query(Disease.name, func.count(CellMarkerEntry.id).label("cnt"))
        .join(CellMarkerEntry, Disease.id == CellMarkerEntry.disease_id)
        .group_by(Disease.name)
        .order_by(func.count(CellMarkerEntry.id).desc())
        .limit(30)
        .all()
    )
    tissue_dist = (
        db.query(Tissue.name, func.count(CellMarkerEntry.id).label("cnt"))
        .join(CellMarkerEntry, Tissue.id == CellMarkerEntry.tissue_id)
        .filter(Tissue.name != "Not specified")
        .group_by(Tissue.name)
        .order_by(func.count(CellMarkerEntry.id).desc())
        .limit(15)
        .all()
    )
    return DistributionData(
        cell_types=[DistributionItem(name=r[0], count=r[1]) for r in cell_type_dist],
        diseases=[DistributionItem(name=r[0], count=r[1]) for r in disease_dist],
        tissues=[DistributionItem(name=r[0], count=r[1]) for r in tissue_dist],
    )


@router.get("/dashboard", response_model=DashboardData)
def dashboard(db: Session = Depends(get_db)):
    """Single endpoint for Dashboard page — overview + distribution in one call."""
    return DashboardData(
        overview=_build_overview(db),
        distribution=_build_distribution(db),
    )


@router.get("/filters", response_model=FilterOptions)
def filter_options(
    cell_type: Optional[list[str]] = Query(None),
    cell_subtype: Optional[list[str]] = Query(None),
    tissue: Optional[list[str]] = Query(None),
    disease: Optional[list[str]] = Query(None),
    db: Session = Depends(get_db),
):
    """返回可用的筛选选项。
    每个字段的可选项只受 *其他* 字段的已选值约束，不受自身约束，
    从而允许用户在同一字段中继续添加更多选项。
    """
    no_filters = not cell_type and not cell_subtype and not tissue and not disease
    if no_filters:
        return FilterOptions(
            cell_types=sorted(r[0] for r in db.query(CellType.name).all()),
            subtypes=sorted(r[0] for r in db.query(CellSubtype.name).all()),
            tissues=sorted(r[0] for r in db.query(Tissue.name).all()),
            diseases=sorted(r[0] for r in db.query(Disease.name).all()),
        )

    def _cross_sq(*, skip: str):
        q = db.query(CellMarkerEntry.id)
        applied = False
        if cell_type and skip != "cell_type":
            q = q.join(CellType, CellMarkerEntry.cell_type_id == CellType.id).filter(
                CellType.name.in_(cell_type)
            )
            applied = True
        if cell_subtype and skip != "cell_subtype":
            q = q.join(
                CellSubtype, CellMarkerEntry.cell_subtype_id == CellSubtype.id
            ).filter(CellSubtype.name.in_(cell_subtype))
            applied = True
        if tissue and skip != "tissue":
            q = q.join(Tissue, CellMarkerEntry.tissue_id == Tissue.id).filter(
                Tissue.name.in_(tissue)
            )
            applied = True
        if disease and skip != "disease":
            q = q.join(Disease, CellMarkerEntry.disease_id == Disease.id).filter(
                Disease.name.in_(disease)
            )
            applied = True
        return q.scalar_subquery() if applied else None

    def _opts(model, name_col, fk_col, sq):
        q = db.query(distinct(name_col)).join(
            CellMarkerEntry, model.id == fk_col
        )
        if sq is not None:
            q = q.filter(CellMarkerEntry.id.in_(sq))
        return sorted(r[0] for r in q.all())

    return FilterOptions(
        cell_types=_opts(
            CellType, CellType.name,
            CellMarkerEntry.cell_type_id, _cross_sq(skip="cell_type"),
        ),
        subtypes=_opts(
            CellSubtype, CellSubtype.name,
            CellMarkerEntry.cell_subtype_id, _cross_sq(skip="cell_subtype"),
        ),
        tissues=_opts(
            Tissue, Tissue.name,
            CellMarkerEntry.tissue_id, _cross_sq(skip="tissue"),
        ),
        diseases=_opts(
            Disease, Disease.name,
            CellMarkerEntry.disease_id, _cross_sq(skip="disease"),
        ),
    )


@router.get("/bubble", response_model=list[BubblePoint])
def bubble_data(
    limit: int = Query(200, ge=10, le=10000),
    cell_type: Optional[list[str]] = Query(None),
    cell_subtype: Optional[list[str]] = Query(None),
    tissue: Optional[list[str]] = Query(None),
    disease: Optional[list[str]] = Query(None),
    db: Session = Depends(get_db),
):
    query = (
        db.query(
            CellType.name.label("cell_type"),
            Marker.symbol.label("marker"),
            func.count(distinct(CellMarkerEntry.paper_id)).label("count"),
        )
        .join(CellMarkerEntry, CellType.id == CellMarkerEntry.cell_type_id)
        .join(Marker, CellMarkerEntry.marker_id == Marker.id)
    )

    if cell_type:
        query = query.filter(CellType.name.in_(cell_type))
    if cell_subtype:
        query = query.join(
            CellSubtype, CellMarkerEntry.cell_subtype_id == CellSubtype.id
        ).filter(CellSubtype.name.in_(cell_subtype))
    if tissue:
        query = query.join(
            Tissue, CellMarkerEntry.tissue_id == Tissue.id
        ).filter(Tissue.name.in_(tissue))
    if disease:
        query = query.join(
            Disease, CellMarkerEntry.disease_id == Disease.id
        ).filter(Disease.name.in_(disease))

    rows = (
        query.group_by(CellType.name, Marker.symbol)
        .order_by(func.count(distinct(CellMarkerEntry.paper_id)).desc())
        .limit(limit)
        .all()
    )

    return [
        BubblePoint(cell_type=r.cell_type, marker=r.marker, count=r.count)
        for r in rows
    ]


@router.get("/distribution", response_model=DistributionData)
def distribution_data(db: Session = Depends(get_db)):
    return _build_distribution(db)
