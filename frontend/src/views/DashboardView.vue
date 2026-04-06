<template>
  <div>
    <!-- Hero Banner -->
    <section class="hero">
      <div class="hero-inner">
        <div class="hero-content">
          <h1 class="hero-title">scMarkerMiner Database</h1>
          <p class="hero-desc">
            A curated repository of single-cell RNA sequencing markers, mined from
            published clinical studies via automated NLP pipelines.
          </p>
          <router-link to="/search" class="hero-btn">
            Explore Markers
            <el-icon style="margin-left:6px"><Search /></el-icon>
          </router-link>
        </div>
        <div class="hero-visual">
          <svg viewBox="0 0 200 200" class="hero-svg">
            <circle cx="100" cy="100" r="80" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="1.5" />
            <circle cx="100" cy="100" r="55" fill="none" stroke="rgba(255,255,255,.1)" stroke-width="1" />
            <circle cx="100" cy="100" r="30" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="1" />
            <circle cx="60" cy="70" r="8" fill="rgba(126,184,247,.5)" />
            <circle cx="130" cy="60" r="6" fill="rgba(16,185,129,.4)" />
            <circle cx="140" cy="120" r="10" fill="rgba(245,158,11,.35)" />
            <circle cx="70" cy="140" r="7" fill="rgba(139,92,246,.4)" />
            <circle cx="110" cy="95" r="5" fill="rgba(255,255,255,.3)" />
            <circle cx="85" cy="110" r="9" fill="rgba(20,184,166,.35)" />
          </svg>
        </div>
      </div>
    </section>

    <!-- Data Summary -->
    <div class="page-container">
      <div class="section-title">Data Portal Summary</div>
      <div class="stat-grid">
        <div v-for="item in statCards" :key="item.label" class="stat-card">
          <div class="stat-icon" :style="{ background: item.color }">
            <svg v-if="item.cellIcon" viewBox="0 0 24 24" width="22" height="22">
              <circle cx="12" cy="12" r="9.5" fill="none" stroke="currentColor" stroke-width="1.6" opacity=".85" />
              <circle cx="10" cy="11" r="3.5" fill="currentColor" opacity=".7" />
              <circle cx="15" cy="8" r="1.2" fill="currentColor" opacity=".4" />
              <circle cx="16" cy="15" r="1" fill="currentColor" opacity=".35" />
            </svg>
            <svg v-else-if="item.tissueIcon" viewBox="0 0 24 24" width="22" height="22"
                 stroke="currentColor" fill="none" stroke-linecap="round">
              <path d="M12 2v7" stroke-width="2.2" />
              <path d="M12 9 Q8 13 6 21" stroke-width="1.7" />
              <path d="M12 9 Q16 13 18 21" stroke-width="1.7" />
              <path d="M8.2 14 Q5.5 13.5 3.5 16" stroke-width="1.2" opacity=".55" />
              <path d="M15.8 14 Q18.5 13.5 20.5 16" stroke-width="1.2" opacity=".55" />
            </svg>
            <el-icon v-else :size="22"><component :is="item.icon" /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-number">{{ item.value?.toLocaleString() ?? '—' }}</div>
            <div class="stat-label">{{ item.label }}</div>
          </div>
        </div>
      </div>

      <!-- Distribution Charts -->
      <div class="section-title" style="margin-top: 40px">Data Distribution</div>

      <!-- Row 1: Cell Type pie + Tissue horizontal bar -->
      <div class="chart-row-top">
        <div class="chart-card chart-card-half">
          <div class="chart-card-header">Cell Type Distribution</div>
          <div ref="cellTypePieRef" class="chart-body"></div>
        </div>
        <div class="chart-card chart-card-half">
          <div class="chart-card-header">Tissue Distribution</div>
          <div ref="tissueBarRef" class="chart-body"></div>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, markRaw } from 'vue'
import { Search, Document, Coin, FirstAidKit, List } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { getOverview, getDistribution } from '../api'

const statCards = ref([
  { label: 'Papers',     value: null, icon: markRaw(Document),        color: 'linear-gradient(135deg,#2e77d0,#5a9ae6)' },
  { label: 'Markers',    value: null, icon: markRaw(Coin),            color: 'linear-gradient(135deg,#10b981,#34d399)' },
  { label: 'Cell Types', value: null, cellIcon: true,                 color: 'linear-gradient(135deg,#8b5cf6,#a78bfa)' },
  { label: 'Diseases',   value: null, icon: markRaw(FirstAidKit),     color: 'linear-gradient(135deg,#f59e0b,#fbbf24)' },
  { label: 'Tissues',    value: null, tissueIcon: true,               color: 'linear-gradient(135deg,#14b8a6,#2dd4bf)' },
  { label: 'Entries',    value: null, icon: markRaw(List),            color: 'linear-gradient(135deg,#ef4444,#f87171)' },
])

const cellTypePieRef = ref(null)
const tissueBarRef   = ref(null)
let cellTypePie = null
let tissueBar   = null

const COLORS = [
  '#2e77d0', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#14b8a6', '#f97316', '#6366f1', '#ec4899', '#84cc16',
  '#06b6d4', '#e11d48', '#a855f7', '#22c55e', '#eab308',
]

function renderPie(el, data) {
  if (!el || !data.length) return null
  const chart = echarts.init(el)
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: {
      type: 'plain',
      orient: 'vertical',
      right: 10,
      top: 'middle',
      textStyle: { fontSize: 12, color: '#6b7280' },
      formatter: name => name.length > 20 ? name.slice(0, 18) + '…' : name,
      itemGap: 10,
    },
    series: [{
      type: 'pie',
      radius: ['30%', '72%'],
      center: ['32%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 5, borderColor: '#fff', borderWidth: 2 },
      label: { show: false },
      emphasis: { label: { show: false } },
      data: data.map(d => ({ name: d.name, value: d.count })),
      color: COLORS,
    }],
  })
  return chart
}

function renderHorizontalBar(el, data) {
  if (!el || !data.length) return null
  const chart = echarts.init(el)
  const sorted = [...data].sort((a, b) => a.count - b.count)
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 140, right: 40, top: 16, bottom: 16 },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#6b7280', fontSize: 11 },
      splitLine: { lineStyle: { color: '#f0f0f0' } },
    },
    yAxis: {
      type: 'category',
      data: sorted.map(d => d.name),
      axisLabel: {
        color: '#374151', fontSize: 12, width: 120, overflow: 'truncate',
      },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    series: [{
      type: 'bar',
      data: sorted.map((d, i) => ({
        value: d.count,
        itemStyle: { color: COLORS[i % COLORS.length], borderRadius: [0, 4, 4, 0] },
      })),
      barMaxWidth: 22,
      label: { show: true, position: 'right', fontSize: 11, color: '#6b7280' },
    }],
  })
  return chart
}

function handleResize() {
  cellTypePie?.resize()
  tissueBar?.resize()
}

onMounted(async () => {
  const [overviewRes, distRes] = await Promise.all([getOverview(), getDistribution()])

  const s = overviewRes.data
  const vals = [s.total_papers, s.total_markers, s.total_cell_types, s.total_diseases, s.total_tissues, s.total_entries]
  statCards.value = statCards.value.map((c, i) => ({ ...c, value: vals[i] }))

  const d = distRes.data
  cellTypePie = renderPie(cellTypePieRef.value, d.cell_types)
  tissueBar   = renderHorizontalBar(tissueBarRef.value, d.tissues)

  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  cellTypePie?.dispose()
  tissueBar?.dispose()
})
</script>

<style scoped>
.hero {
  background: linear-gradient(135deg, #1b3a5c 0%, #1a5bb5 50%, #2e77d0 100%);
  color: #fff;
  position: relative;
  overflow: hidden;
}

.hero-inner {
  max-width: 1400px;
  margin: 0 auto;
  padding: 60px 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 40px;
}

.hero-content { max-width: 600px; }

.hero-title {
  font-size: 36px;
  font-weight: 800;
  letter-spacing: -0.5px;
  line-height: 1.2;
}

.hero-desc {
  margin-top: 16px;
  font-size: 15px;
  line-height: 1.7;
  color: rgba(255,255,255,.75);
}

.hero-btn {
  display: inline-flex;
  align-items: center;
  margin-top: 28px;
  padding: 11px 28px;
  background: rgba(255,255,255,.15);
  border: 1px solid rgba(255,255,255,.3);
  border-radius: 8px;
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  text-decoration: none;
  transition: all .2s;
  backdrop-filter: blur(4px);
}

.hero-btn:hover {
  background: rgba(255,255,255,.25);
  color: #fff;
}

.hero-visual { flex-shrink: 0; }

.hero-svg {
  width: 200px;
  height: 200px;
  animation: spin-slow 40s linear infinite;
}

@keyframes spin-slow { to { transform: rotate(360deg); } }

.section-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 20px;
  padding-left: 12px;
  border-left: 4px solid var(--primary);
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
}

.stat-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow .2s, transform .2s;
}

.stat-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.stat-icon {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.stat-number {
  font-size: 24px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.1;
}

.stat-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 3px;
}

/* ---- Chart layout ---- */
.chart-row-top {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
}

.chart-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.chart-card-header {
  padding: 16px 20px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
}

.chart-body {
  height: 440px;
  padding: 8px;
}


@media (max-width: 1200px) {
  .hero-inner { padding: 40px 20px; }
  .stat-grid { grid-template-columns: repeat(3, 1fr); }
  .chart-row-top { grid-template-columns: 1fr; }
  .hero-visual { display: none; }
}

@media (max-width: 768px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .hero-title { font-size: 26px; }
}
</style>
