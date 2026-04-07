<template>
  <div class="page-container" v-loading="loading">
    <!-- Marker header -->
    <div class="detail-header">
      <div class="detail-header-left">
        <el-button @click="$router.back()" text class="back-btn">
          <el-icon style="margin-right:4px"><ArrowLeft /></el-icon> Back
        </el-button>
        <h2 class="detail-title">{{ detail.symbol || '…' }}</h2>
        <span class="detail-cite">Cited by {{ detail.citation_count ?? '—' }} papers</span>
      </div>
    </div>

    <!-- Summary cards -->
    <div class="summary-grid">
      <div class="summary-card">
        <div class="summary-card-header">
          <span class="summary-card-icon" style="background: linear-gradient(135deg,#2e77d0,#5a9ae6)">
            <svg viewBox="0 0 24 24" width="16" height="16">
              <circle cx="12" cy="12" r="9.5" fill="none" stroke="currentColor" stroke-width="1.6" opacity=".85" />
              <circle cx="10" cy="11" r="3.5" fill="currentColor" opacity=".7" />
              <circle cx="15" cy="8" r="1.2" fill="currentColor" opacity=".4" />
              <circle cx="16" cy="15" r="1" fill="currentColor" opacity=".35" />
            </svg>
          </span>
          Cell Types
        </div>
        <div class="summary-card-body">
          <el-tag v-for="c in detail.cell_types" :key="c" class="detail-tag" round>{{ c }}</el-tag>
          <span v-if="!detail.cell_types?.length" class="empty-text">—</span>
        </div>
      </div>

      <div class="summary-card">
        <div class="summary-card-header">
          <span class="summary-card-icon" style="background: linear-gradient(135deg,#8b5cf6,#a78bfa)">
            <el-icon :size="16"><Share /></el-icon>
          </span>
          Subtypes
        </div>
        <div class="summary-card-body">
          <el-tag v-for="s in detail.subtypes" :key="s" class="detail-tag" type="info" round>{{ s }}</el-tag>
          <span v-if="!detail.subtypes?.length" class="empty-text">—</span>
        </div>
      </div>

      <div class="summary-card">
        <div class="summary-card-header">
          <span class="summary-card-icon" style="background: linear-gradient(135deg,#10b981,#34d399)">
            <svg viewBox="0 0 24 24" width="16" height="16"
                 stroke="currentColor" fill="none" stroke-linecap="round">
              <path d="M12 2v7" stroke-width="2.2" />
              <path d="M12 9 Q8 13 6 21" stroke-width="1.7" />
              <path d="M12 9 Q16 13 18 21" stroke-width="1.7" />
              <path d="M8.2 14 Q5.5 13.5 3.5 16" stroke-width="1.2" opacity=".55" />
              <path d="M15.8 14 Q18.5 13.5 20.5 16" stroke-width="1.2" opacity=".55" />
            </svg>
          </span>
          Tissues
        </div>
        <div class="summary-card-body">
          <el-tag v-for="t in detail.tissues" :key="t" class="detail-tag" type="success" round>{{ t }}</el-tag>
          <span v-if="!detail.tissues?.length" class="empty-text">—</span>
        </div>
      </div>

      <div class="summary-card">
        <div class="summary-card-header">
          <span class="summary-card-icon" style="background: linear-gradient(135deg,#f59e0b,#fbbf24)">
            <el-icon :size="16"><FirstAidKit /></el-icon>
          </span>
          Diseases
        </div>
        <div class="summary-card-body">
          <el-tag v-for="d in detail.diseases" :key="d" class="detail-tag" type="warning" round>{{ d }}</el-tag>
          <span v-if="!detail.diseases?.length" class="empty-text">—</span>
        </div>
      </div>
    </div>

    <!-- Entries table -->
    <div class="entries-card">
      <div class="entries-header">All entries from literature</div>
      <el-table :data="entries" v-loading="entriesLoading" stripe size="small"
                :header-cell-style="{ background: '#f8fafc', color: '#374151', fontWeight: 600 }">
        <el-table-column prop="cell_type" label="Cell Type" width="140" />
        <el-table-column prop="cell_subtype" label="Subtype" min-width="180" show-overflow-tooltip />
        <el-table-column prop="tissue" label="Tissue" width="120" />
        <el-table-column prop="disease" label="Disease" min-width="160" show-overflow-tooltip />
        <el-table-column prop="pmcid" label="PMCID" width="130">
          <template #default="{ row }">
            <a :href="`https://www.ncbi.nlm.nih.gov/pmc/articles/PMC${row.pmcid}/`"
               target="_blank" class="pmcid-link">
              PMC{{ row.pmcid }}
            </a>
          </template>
        </el-table-column>
      </el-table>
      <div class="entries-footer">
        <span class="entry-count">{{ totalEntries }} entries total</span>
        <el-pagination
          v-model:current-page="entryPage"
          :page-size="entryPageSize"
          :total="totalEntries"
          layout="prev, pager, next, jumper"
          @current-change="fetchEntries"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Share, FirstAidKit } from '@element-plus/icons-vue'
import { getMarkerDetail } from '../api'

const route = useRoute()
const loading = ref(true)
const entriesLoading = ref(false)
const detail = ref({})

const entryPage = ref(1)
const entryPageSize = 20
const entries = ref([])
const totalEntries = ref(0)

async function fetchEntries(pg) {
  if (pg != null) entryPage.value = pg
  entriesLoading.value = true
  try {
    const res = await getMarkerDetail(route.params.symbol, {
      page: entryPage.value,
      page_size: entryPageSize,
    })
    entries.value = res.data.entries
    totalEntries.value = res.data.total_entries
    if (!detail.value.symbol) detail.value = res.data
  } finally {
    entriesLoading.value = false
  }
}

onMounted(async () => {
  try {
    const res = await getMarkerDetail(route.params.symbol)
    detail.value = res.data
    entries.value = res.data.entries
    totalEntries.value = res.data.total_entries
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.detail-header {
  margin-bottom: 28px;
}

.detail-header-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.back-btn {
  color: var(--text-secondary);
  font-size: 14px;
  padding: 6px 10px;
}

.detail-title {
  font-size: 28px;
  font-weight: 800;
  color: var(--primary-dark);
}

.detail-cite {
  font-size: 14px;
  color: var(--text-secondary);
  background: #f0f7ff;
  padding: 4px 12px;
  border-radius: 20px;
}

/* ---- Summary cards ---- */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.summary-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.summary-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
}

.summary-card-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.summary-card-body {
  padding: 14px 18px;
  height: 180px;
  overflow-y: auto;
}

.detail-tag {
  margin: 3px;
}

.empty-text {
  color: var(--text-light);
}

/* ---- Entries card ---- */
.entries-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.entries-header {
  padding: 16px 20px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
}

.pmcid-link {
  color: var(--primary);
  font-size: 13px;
}

.entries-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  border-top: 1px solid var(--border-color);
}

.entry-count {
  font-size: 13px;
  color: var(--text-secondary);
}

@media (max-width: 1000px) {
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 600px) {
  .summary-grid { grid-template-columns: 1fr; }
  .detail-title { font-size: 22px; }
}
</style>
