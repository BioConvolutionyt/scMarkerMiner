"""
api/routes/stats.py — 统计概览、筛选选项、可视化数据接口
"""

import time
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, distinct, text
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas import (
    OverviewStats,
    BubblePoint,
    FilterOptions,
    DistributionItem,
    DistributionData,
    DashboardData,
    SearchInitData,
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

# ---------------------------------------------------------------------------
# TTL in-memory cache — survives Vercel warm starts, auto-expires after TTL
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[object, float]] = {}
_CACHE_TTL = 300  # 5 minutes

def _get_cached(key: str, builder, ttl: int = _CACHE_TTL):
    now = time.time()
    hit = _cache.get(key)
    if hit is not None:
        val, ts = hit
        if now - ts < ttl:
            return val
    val = builder()
    _cache[key] = (val, now)
    return val


@router.get("/overview", response_model=OverviewStats)
def overview(db: Session = Depends(get_db)):
    return _build_overview(db)


def _build_overview(db: Session) -> OverviewStats:
    row = db.execute(text(
        "SELECT "
        "(SELECT COUNT(*) FROM papers) AS p, "
        "(SELECT COUNT(*) FROM markers) AS m, "
        "(SELECT COUNT(*) FROM cell_types) AS ct, "
        "(SELECT COUNT(*) FROM diseases) AS d, "
        "(SELECT COUNT(*) FROM tissues) AS t, "
        "(SELECT COUNT(*) FROM cell_marker_entries) AS e"
    )).mappings().one()
    return OverviewStats(
        total_papers=row["p"], total_markers=row["m"],
        total_cell_types=row["ct"], total_diseases=row["d"],
        total_tissues=row["t"], total_entries=row["e"],
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
    return _get_cached("dashboard", lambda: DashboardData(
        overview=_build_overview(db),
        distribution=_build_distribution(db),
    ))


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
        return _get_cached("filters_all", lambda: FilterOptions(
            cell_types=sorted(r[0] for r in db.query(CellType.name).all()),
            subtypes=sorted(r[0] for r in db.query(CellSubtype.name).all()),
            tissues=sorted(r[0] for r in db.query(Tissue.name).all()),
            diseases=sorted(r[0] for r in db.query(Disease.name).all()),
        ))

    import hashlib, json as _json
    cache_key = "filters_" + hashlib.md5(
        _json.dumps({"ct": cell_type, "cs": cell_subtype, "t": tissue, "d": disease},
                     sort_keys=True).encode()
    ).hexdigest()

    def _build_filtered():
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

    return _get_cached(cache_key, _build_filtered, ttl=120)


def do_bubble(
    db: Session, limit=200,
    cell_type=None, cell_subtype=None, tissue=None, disease=None,
) -> list[BubblePoint]:
    """Core bubble logic, usable from both the route and the init endpoint."""
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


@router.get("/bubble", response_model=list[BubblePoint])
def bubble_data(
    limit: int = Query(200, ge=10, le=10000),
    cell_type: Optional[list[str]] = Query(None),
    cell_subtype: Optional[list[str]] = Query(None),
    tissue: Optional[list[str]] = Query(None),
    disease: Optional[list[str]] = Query(None),
    db: Session = Depends(get_db),
):
    return do_bubble(db, limit, cell_type, cell_subtype, tissue, disease)


@router.get("/search-init", response_model=SearchInitData)
def search_init(db: Session = Depends(get_db)):
    """Combined endpoint for search page initial load.
    Returns filters + default search results + bubble data in a single call,
    reducing 3 cold starts to 1.
    """
    from api.routes.markers import do_search

    return _get_cached("search_init", lambda: SearchInitData(
        filters=FilterOptions(
            cell_types=sorted(r[0] for r in db.query(CellType.name).all()),
            subtypes=sorted(r[0] for r in db.query(CellSubtype.name).all()),
            tissues=sorted(r[0] for r in db.query(Tissue.name).all()),
            diseases=sorted(r[0] for r in db.query(Disease.name).all()),
        ),
        search=do_search(db),
        bubble=do_bubble(db, limit=2000),
    ))


@router.get("/distribution", response_model=DistributionData)
def distribution_data(db: Session = Depends(get_db)):
    return _build_distribution(db)
