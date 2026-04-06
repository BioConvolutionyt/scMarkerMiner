"""
api/schemas.py — Pydantic 响应模型
"""

from typing import Optional
from pydantic import BaseModel


# =====================================================================
# Marker 检索
# =====================================================================

class MarkerEntryItem(BaseModel):
    marker: str
    cell_type: str
    cell_subtype: Optional[str] = None
    tissue: Optional[str] = None
    disease: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: str
    marker_status: Optional[str] = None


class MarkerSearchResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: list[MarkerEntryItem]


# =====================================================================
# Marker 可信度排行
# =====================================================================

class MarkerRankingItem(BaseModel):
    symbol: str
    citation_count: int
    cell_type_count: int
    cell_types: list[str]
    tissues: list[str]
    diseases: list[str]


class MarkerRankingResponse(BaseModel):
    total: int
    results: list[MarkerRankingItem]


# =====================================================================
# Marker 详情
# =====================================================================

class MarkerDetailResponse(BaseModel):
    symbol: str
    citation_count: int
    cell_types: list[str]
    subtypes: list[str]
    tissues: list[str]
    diseases: list[str]
    entries: list[MarkerEntryItem]


# =====================================================================
# 细胞类型
# =====================================================================

class CellTypeItem(BaseModel):
    name: str
    marker_count: int
    entry_count: int
    subtypes: list[str]


class CellTypeListResponse(BaseModel):
    total: int
    results: list[CellTypeItem]


# =====================================================================
# 统计概览
# =====================================================================

class OverviewStats(BaseModel):
    total_papers: int
    total_markers: int
    total_cell_types: int
    total_diseases: int
    total_tissues: int
    total_entries: int


# =====================================================================
# 可视化：气泡图 & 热图
# =====================================================================

class BubblePoint(BaseModel):
    cell_type: str
    marker: str
    count: int


class HeatmapPoint(BaseModel):
    marker: str
    tissue: str
    count: int


# =====================================================================
# 筛选器选项
# =====================================================================

class FilterOptions(BaseModel):
    cell_types: list[str]
    subtypes: list[str]
    tissues: list[str]
    diseases: list[str]


class DistributionItem(BaseModel):
    name: str
    count: int


class DistributionData(BaseModel):
    cell_types: list[DistributionItem]
    diseases: list[DistributionItem]
    tissues: list[DistributionItem]


class DashboardData(BaseModel):
    overview: OverviewStats
    distribution: DistributionData
