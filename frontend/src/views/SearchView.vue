<template>
  <div class="page-container">
    <div class="search-header">
      <h2>Marker Search</h2>
      <p>Multi-dimensional filtering across cell types, subtypes, tissues, diseases and markers</p>
    </div>

    <div class="filter-card">
      <div class="filter-row">
        <el-select-v2 v-model="filters.cell_type" :options="cellTypeOpts" placeholder="Cell Type"
                       multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="8"
                       clearable filterable class="filter-select" @change="onFilterChange" />
        <el-select-v2 v-model="filters.cell_subtype" :options="subtypeOpts" placeholder="Cell Subtype"
                       multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="8"
                       clearable filterable class="filter-select" @change="onFilterChange" />
        <el-select-v2 v-model="filters.tissue" :options="tissueOpts" placeholder="Tissue"
                       multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="8"
                       clearable filterable class="filter-select" @change="onFilterChange" />
      </div>
      <div class="filter-row">
        <el-select-v2 v-model="filters.disease" :options="diseaseOpts" placeholder="Disease"
                       multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="8"
                       clearable filterable class="filter-select-disease" @change="onFilterChange" />
        <el-input v-model="filters.marker" placeholder="Marker symbol…" clearable
                  class="filter-marker" @keyup.enter="doSearch" />
        <el-button type="primary" @click="doSearch" class="btn-search">Search</el-button>
        <el-button @click="resetFilters">Reset</el-button>
      </div>
    </div>

    <div class="result-card">
      <el-table :data="results" v-loading="loading" stripe size="small" style="width: 100%"
                :header-cell-style="{ background: '#f8fafc', color: '#374151', fontWeight: 600 }">
        <el-table-column prop="marker" label="Marker" width="110">
          <template #default="{ row }">
            <router-link :to="`/marker/${row.marker}`" class="marker-link">
              {{ row.marker }}
            </router-link>
          </template>
        </el-table-column>
        <el-table-column prop="cell_type" label="Cell Type" width="150" />
        <el-table-column prop="cell_subtype" label="Subtype" width="240" show-overflow-tooltip />
        <el-table-column prop="tissue" label="Tissue" width="120" />
        <el-table-column prop="disease" label="Disease" min-width="200" show-overflow-tooltip />
        <el-table-column prop="pmcid" label="PMCID" width="120">
          <template #default="{ row }">
            <a :href="`https://www.ncbi.nlm.nih.gov/pmc/articles/PMC${row.pmcid}/`"
               target="_blank" class="pmcid-link">
              PMC{{ row.pmcid }}
            </a>
          </template>
        </el-table-column>
        <el-table-column prop="marker_status" label="Validation Status" width="130">
          <template #default="{ row }">
            <el-tag :type="statusType(row.marker_status)" size="small" round>{{ row.marker_status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>

      <div class="result-footer">
        <span class="result-count">{{ total }} results found</span>
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next, jumper"
          @current-change="doSearch"
        />
      </div>
    </div>

    <!-- Bubble chart + Ranking panel -->
    <div class="viz-card" v-if="bubbleVisible">
      <div class="viz-header">
        <div>
          <span class="viz-title">Cell Type – Marker Distribution</span>
          <span class="viz-sub">
            {{ hasActiveFilters ? 'Filtered by current search conditions' : 'Top markers across all cell types' }}
          </span>
        </div>
        <el-dropdown v-if="hasActiveFilters" @command="exportRanking">
          <el-button size="small" type="primary" round>
            Export <el-icon style="margin-left:4px"><Download /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="csv">Download CSV</el-dropdown-item>
              <el-dropdown-item command="xlsx">Download Excel</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>

      <div class="viz-body">
        <div ref="bubbleRef" class="bubble-area"></div>

        <div v-if="hasActiveFilters" class="ranking-panel">
          <div class="ranking-title">All Markers by Cell Type</div>
          <div class="ranking-scroll">
            <template v-for="group in rankingGroups" :key="group.cell_type">
              <div class="ranking-group-header">
                {{ group.cell_type }}
                <span class="ranking-group-count">{{ group.markers.length }}</span>
              </div>
              <div v-for="item in group.markers" :key="`${group.cell_type}_${item.marker}`"
                   class="ranking-item"
                   :class="{ active: highlightMarker === item.marker }"
                   :data-key="`${group.cell_type}||${item.marker}`"
                   @mouseenter="onRankHover(item.marker)"
                   @mouseleave="onRankLeave()">
                <div class="ranking-body">
                  <div class="ranking-top-row">
                    <router-link :to="`/marker/${item.marker}`" class="ranking-link">
                      {{ item.marker }}
                    </router-link>
                    <el-icon class="copy-icon" @click.prevent="copyMarker(item.marker)" title="Copy symbol">
                      <DocumentCopy />
                    </el-icon>
                  </div>
                  <div class="ranking-bar-row">
                    <div class="ranking-bar-bg">
                      <div class="ranking-bar" :style="{ width: barWidth(item.count) }"></div>
                    </div>
                    <span class="ranking-count">{{ item.count }} cited</span>
                  </div>
                </div>
              </div>
            </template>
            <div v-if="hasMoreRanking" class="ranking-load-more" @click="rankingLimit += RANKING_PAGE_SIZE">
              Load more ({{ rankingTotalCount - rankingRenderedCount }} remaining)
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Download, DocumentCopy } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { init as echartsInit, use } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
use([ScatterChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])
import { searchMarkers, getFilters, getBubbleData, getSearchInit } from '../api'

const loading = ref(false)
const results = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

const allBubbleData = ref([])
const bubbleVisible = computed(() => allBubbleData.value.length > 0)
const chartBubbleData = computed(() => allBubbleData.value.slice(0, 200))
let lastBubbleKey = ''
let totalKnown = false

const filters = ref({ cell_type: [], cell_subtype: [], tissue: [], disease: [], marker: '' })
const options = ref({ cell_types: [], subtypes: [], tissues: [], diseases: [] })

const toOpts = (list) => list.map(v => ({ value: v, label: v }))
const cellTypeOpts = computed(() => toOpts(options.value.cell_types))
const subtypeOpts  = computed(() => toOpts(options.value.subtypes))
const tissueOpts   = computed(() => toOpts(options.value.tissues))
const diseaseOpts  = computed(() => toOpts(options.value.diseases))

const bubbleRef = ref(null)
let bubbleChart = null

const highlightMarker = ref(null)

const hasActiveFilters = computed(() =>
  filters.value.cell_type.length > 0 || filters.value.cell_subtype.length > 0 ||
  filters.value.tissue.length > 0 || filters.value.disease.length > 0 || filters.value.marker
)

const statusType = (s) =>
  ({ approved: 'success', corrected: 'warning', ambiguous: 'danger', unknown: 'info' }[s] || 'info')

// ---- Ranking ----

const RANKING_PAGE_SIZE = 500
const rankingLimit = ref(RANKING_PAGE_SIZE)

const rankingGroupsFull = computed(() => {
  const groups = {}
  for (const d of allBubbleData.value) {
    if (!groups[d.cell_type]) groups[d.cell_type] = []
    groups[d.cell_type].push({ marker: d.marker, count: d.count })
  }
  return Object.entries(groups)
    .map(([ct, markers]) => ({
      cell_type: ct,
      markers: markers.sort((a, b) => b.count - a.count),
    }))
    .sort((a, b) => b.markers.length - a.markers.length)
})

const bubbleMarkerKeys = computed(() =>
  new Set(chartBubbleData.value.map(d => `${d.cell_type}||${d.marker}`))
)

const rankingGroups = computed(() => {
  const limit = rankingLimit.value
  const bubbleKeys = bubbleMarkerKeys.value
  let extraCount = 0
  const result = []
  for (const g of rankingGroupsFull.value) {
    const markers = []
    for (const m of g.markers) {
      const inBubble = bubbleKeys.has(`${g.cell_type}||${m.marker}`)
      if (inBubble || extraCount < limit) {
        markers.push(m)
        if (!inBubble) extraCount++
      }
    }
    if (markers.length > 0) {
      result.push({ cell_type: g.cell_type, markers })
    }
  }
  return result
})

const rankingTotalCount = computed(() =>
  rankingGroupsFull.value.reduce((s, g) => s + g.markers.length, 0)
)
const rankingRenderedCount = computed(() =>
  rankingGroups.value.reduce((s, g) => s + g.markers.length, 0)
)
const hasMoreRanking = computed(() => rankingRenderedCount.value < rankingTotalCount.value)

const maxRankCount = computed(() => {
  let m = 1
  for (const d of allBubbleData.value) { if (d.count > m) m = d.count }
  return m
})
const barWidth = (count) => `${(count / maxRankCount.value) * 100}%`

// ---- Copy helper ----

async function copyMarker(symbol) {
  try {
    await navigator.clipboard.writeText(symbol)
    ElMessage({ message: `Copied: ${symbol}`, type: 'success', duration: 1500 })
  } catch {
    ElMessage.error('Copy failed')
  }
}

// ---- Export ranking ----

async function exportRanking(fmt) {
  const rows = []
  for (const g of rankingGroupsFull.value) {
    for (const m of g.markers) {
      rows.push({ 'Cell Type': g.cell_type, Marker: m.marker, Citations: m.count })
    }
  }
  if (!rows.length) return

  if (fmt === 'xlsx') {
    const XLSX = await import('xlsx')
    const ws = XLSX.utils.json_to_sheet(rows)
    ws['!cols'] = [{ wch: 28 }, { wch: 14 }, { wch: 10 }]
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, 'Markers')
    XLSX.writeFile(wb, 'marker_ranking.xlsx')
  } else {
    let csv = '\uFEFF'
    csv += 'Cell Type,Marker,Citations\n'
    for (const r of rows) {
      const ct = r['Cell Type'].includes(',') ? `"${r['Cell Type']}"` : r['Cell Type']
      csv += `${ct},${r.Marker},${r.Citations}\n`
    }
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'marker_ranking.csv'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }
}

// ---- Ranking ↔ Bubble interactions ----

function onRankHover(marker) {
  highlightMarker.value = marker
  if (!bubbleChart) return
  const indices = []
  chartBubbleData.value.forEach((d, i) => { if (d.marker === marker) indices.push(i) })
  if (indices.length) {
    bubbleChart.dispatchAction({ type: 'highlight', seriesIndex: 0, dataIndex: indices })
  }
}

function onRankLeave() {
  highlightMarker.value = null
  if (!bubbleChart) return
  bubbleChart.dispatchAction({ type: 'downplay', seriesIndex: 0 })
}

function scrollRankIntoView(marker, cellType) {
  const key = cellType ? `${cellType}||${marker}` : marker
  const selector = cellType
    ? `.ranking-item[data-key="${CSS.escape(key)}"]`
    : `.ranking-item[data-key$="||${CSS.escape(marker)}"]`
  const el = document.querySelector(selector)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

// ---- Filter / search plumbing ----

function buildFilterParams() {
  const p = {}
  if (filters.value.cell_type?.length)    p.cell_type    = filters.value.cell_type
  if (filters.value.cell_subtype?.length) p.cell_subtype = filters.value.cell_subtype
  if (filters.value.tissue?.length)       p.tissue       = filters.value.tissue
  if (filters.value.disease?.length)      p.disease      = filters.value.disease
  return p
}

function buildSearchParams() {
  const p = { ...buildFilterParams(), page: page.value, page_size: pageSize }
  if (filters.value.marker) p.marker = filters.value.marker
  if (totalKnown && total.value > 0) p.total_hint = total.value
  return p
}

async function fetchFilterOptions(depth = 0) {
  if (depth > 3) return
  const res = await getFilters(buildFilterParams())
  options.value = res.data

  let changed = false
  const reconcile = (arr, available) => {
    const kept = arr.filter(v => available.includes(v))
    if (kept.length !== arr.length) { changed = true; return kept }
    return arr
  }
  filters.value.cell_type    = reconcile(filters.value.cell_type,    res.data.cell_types)
  filters.value.cell_subtype = reconcile(filters.value.cell_subtype, res.data.subtypes)
  filters.value.tissue       = reconcile(filters.value.tissue,       res.data.tissues)
  filters.value.disease      = reconcile(filters.value.disease,      res.data.diseases)

  if (changed) await fetchFilterOptions(depth + 1)
}

let _filterTimer = null
function onFilterChange() {
  page.value = 1
  lastBubbleKey = ''
  totalKnown = false
  clearTimeout(_filterTimer)
  _filterTimer = setTimeout(async () => {
    const filterParams = buildFilterParams()
    const [filtersRes] = await Promise.all([
      getFilters(filterParams),
      doSearch(),
    ])
    options.value = filtersRes.data

    let changed = false
    const reconcile = (arr, available) => {
      const kept = arr.filter(v => available.includes(v))
      if (kept.length !== arr.length) { changed = true; return kept }
      return arr
    }
    filters.value.cell_type    = reconcile(filters.value.cell_type,    filtersRes.data.cell_types)
    filters.value.cell_subtype = reconcile(filters.value.cell_subtype, filtersRes.data.subtypes)
    filters.value.tissue       = reconcile(filters.value.tissue,       filtersRes.data.tissues)
    filters.value.disease      = reconcile(filters.value.disease,      filtersRes.data.diseases)

    if (changed) {
      lastBubbleKey = ''
      await fetchFilterOptions()
      await doSearch()
    }
  }, 300)
}

async function doSearch() {
  loading.value = true
  try {
    const filterParams = buildFilterParams()
    const bubbleKey = JSON.stringify(filterParams)
    const needBubble = bubbleKey !== lastBubbleKey

    const promises = [searchMarkers(buildSearchParams())]
    if (needBubble) {
      promises.push(getBubbleData({ ...filterParams, limit: 2000 }))
    }

    const settled = await Promise.all(promises)
    results.value = settled[0].data.results
    total.value = settled[0].data.total
    totalKnown = true

    if (needBubble) {
      allBubbleData.value = settled[1].data
      lastBubbleKey = bubbleKey
      rankingLimit.value = RANKING_PAGE_SIZE
      await nextTick()
      renderBubble(chartBubbleData.value)
    }
  } finally {
    loading.value = false
  }
}

// ---- Bubble chart rendering ----

function buildJitteredData(data, cellTypeList) {
  const groups = {}
  data.forEach((d, i) => {
    const key = `${cellTypeList.indexOf(d.cell_type)}_${d.count}`
    if (!groups[key]) groups[key] = []
    groups[key].push(i)
  })

  return data.map((d, i) => {
    const x = cellTypeList.indexOf(d.cell_type)
    const key = `${x}_${d.count}`
    const group = groups[key]
    if (group.length <= 1) return [x, d.count, d.marker, d.cell_type, d.count]

    const idx = group.indexOf(i)
    const spread = Math.max(d.count * 0.06, 0.4)
    const step = (spread * 2) / Math.max(group.length - 1, 1)
    const offset = (idx - (group.length - 1) / 2) * step
    return [x, d.count + offset, d.marker, d.cell_type, d.count]
  })
}

function renderBubble(data) {
  if (!bubbleRef.value || !data.length) return
  if (!bubbleChart) bubbleChart = echartsInit(bubbleRef.value)

  const cellTypeList = [...new Set(data.map(d => d.cell_type))].sort()
  const maxCount = Math.max(...data.map(d => d.count), 1)
  const seriesData = buildJitteredData(data, cellTypeList)

  bubbleChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: p => {
        const [, , marker, cellType, actualCount] = p.data
        return `<b style="font-size:14px">${marker}</b><br/>Cell Type: ${cellType}<br/>Citations: ${actualCount}`
      },
    },
    xAxis: {
      type: 'category',
      data: cellTypeList,
      axisLabel: { rotate: 40, fontSize: 10, interval: 0 },
      name: 'Cell Type',
      nameLocation: 'center',
      nameGap: 60,
    },
    yAxis: { type: 'value', name: 'Citations' },
    series: [{
      type: 'scatter',
      data: seriesData,
      symbolSize: (val) => Math.max(6, Math.sqrt(val[4] / maxCount) * 45),
      itemStyle: { color: '#2e77d0', opacity: 0.6 },
      emphasis: {
        itemStyle: { opacity: 1, borderColor: '#1a5bb5', borderWidth: 2, shadowBlur: 8, shadowColor: 'rgba(0,0,0,.15)' },
        label: { show: true, formatter: p => p.data[2], fontSize: 13, fontWeight: 'bold', position: 'top', color: '#1b3a5c', opacity: 1, textBorderColor: '#fff', textBorderWidth: 2 },
      },
      label: { show: false },
    }],
    grid: { left: 60, right: 20, bottom: 90, top: 40 },
    dataZoom: [{ type: 'slider', xAxisIndex: 0, bottom: 5, height: 18 }],
  }, true)

  bubbleChart.off('mouseover')
  bubbleChart.off('mouseout')
  bubbleChart.off('click')

  bubbleChart.on('mouseover', { seriesIndex: 0 }, (params) => {
    highlightMarker.value = params.data[2]
  })
  bubbleChart.on('mouseout', { seriesIndex: 0 }, () => {
    highlightMarker.value = null
  })
  bubbleChart.on('click', { seriesIndex: 0 }, (params) => {
    const marker = params.data[2]
    const cellType = params.data[3]
    highlightMarker.value = marker
    scrollRankIntoView(marker, cellType)
  })
}

async function resetFilters() {
  filters.value = { cell_type: [], cell_subtype: [], tissue: [], disease: [], marker: '' }
  page.value = 1
  loading.value = true
  try {
    const res = await getSearchInit()
    const { filters: f, search: s, bubble: b } = res.data
    options.value = f
    results.value = s.results
    total.value = s.total
    totalKnown = true
    allBubbleData.value = b
    lastBubbleKey = JSON.stringify({})
    rankingLimit.value = RANKING_PAGE_SIZE
    await nextTick()
    renderBubble(chartBubbleData.value)
  } finally {
    loading.value = false
  }
}

function handleResize() { bubbleChart?.resize() }

watch(hasActiveFilters, () => {
  nextTick(() => bubbleChart?.resize())
})

onMounted(async () => {
  loading.value = true
  try {
    const res = await getSearchInit()
    const { filters: f, search: s, bubble: b } = res.data
    options.value = f
    results.value = s.results
    total.value = s.total
    totalKnown = true
    allBubbleData.value = b
    lastBubbleKey = JSON.stringify({})
    await nextTick()
    renderBubble(chartBubbleData.value)
  } finally {
    loading.value = false
  }
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  clearTimeout(_filterTimer)
  window.removeEventListener('resize', handleResize)
  bubbleChart?.dispose()
})
</script>

<style scoped>
.search-header {
  margin-bottom: 24px;
}

.search-header h2 {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.search-header p {
  font-size: 14px;
  color: var(--text-secondary);
  margin-top: 4px;
}

/* ---- Filter card ---- */
.filter-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  padding: 20px 24px;
  box-shadow: var(--shadow-sm);
  margin-bottom: 20px;
}

.filter-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.filter-row:last-child { margin-bottom: 0; }

.filter-select { flex: 1; min-width: 0; }

.filter-select-disease { flex: 0 1 400px; min-width: 260px; }

.filter-marker { width: 200px; }

.btn-search {
  background: var(--primary);
  border-color: var(--primary);
}

.filter-select :deep(.el-select-v2__input-wrapper),
.filter-select-disease :deep(.el-select-v2__input-wrapper) {
  flex-wrap: wrap;
}

.filter-select :deep(.el-select-v2__wrapper),
.filter-select-disease :deep(.el-select-v2__wrapper) {
  max-height: 90px;
  overflow-y: auto;
}

.filter-select-disease :deep(.el-select-v2__dropdown) {
  min-width: 400px !important;
}

/* ---- Result card ---- */
.result-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  padding: 0;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.result-card :deep(.el-table) {
  --el-table-border-color: var(--border-color);
}

.marker-link {
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
}

.marker-link:hover { text-decoration: underline; }

.pmcid-link {
  color: var(--primary);
  font-size: 13px;
}

.result-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  border-top: 1px solid var(--border-color);
}

.result-count {
  font-size: 13px;
  color: var(--text-secondary);
}

/* ---- Viz card ---- */
.viz-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  margin-top: 24px;
  overflow: hidden;
}

.viz-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border-color);
}

.viz-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.viz-sub {
  font-size: 12px;
  color: var(--text-light);
  margin-left: 12px;
}

.viz-body {
  display: flex;
}

.bubble-area {
  flex: 1;
  height: 520px;
  min-width: 0;
}

/* ---- Ranking panel ---- */
.ranking-panel {
  width: 280px;
  flex-shrink: 0;
  border-left: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  height: 520px;
}

.ranking-title {
  padding: 10px 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.ranking-scroll {
  flex: 1;
  overflow-y: auto;
}

.ranking-group-header {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f8fafc;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.ranking-group-count {
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  border-radius: 8px;
  padding: 0 7px;
  line-height: 18px;
}

.ranking-item {
  display: flex;
  align-items: flex-start;
  padding: 6px 14px;
  cursor: pointer;
  transition: background-color .15s;
}

.ranking-item:hover,
.ranking-item.active {
  background-color: #eff6ff;
}

.ranking-body { flex: 1; min-width: 0; }

.ranking-top-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ranking-link {
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ranking-link:hover { text-decoration: underline; }

.copy-icon {
  flex-shrink: 0;
  font-size: 13px;
  color: #c0c4cc;
  cursor: pointer;
  transition: color .15s;
}

.copy-icon:hover { color: var(--primary); }

.ranking-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 3px;
}

.ranking-bar-bg {
  flex: 1;
  height: 4px;
  background: #f0f2f5;
  border-radius: 2px;
}

.ranking-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), var(--primary-light));
  border-radius: 2px;
  transition: width .3s;
}

.ranking-count {
  font-size: 11px;
  color: var(--text-light);
  flex-shrink: 0;
  min-width: 24px;
  text-align: right;
}

.ranking-load-more {
  padding: 12px 14px;
  text-align: center;
  font-size: 13px;
  color: var(--primary);
  cursor: pointer;
  font-weight: 500;
  border-top: 1px solid var(--border-color);
}

.ranking-load-more:hover {
  background: #eff6ff;
}
</style>
