<template>
  <div class="app-layout">
    <header class="app-header">
      <div class="header-inner">
        <router-link to="/" class="header-brand">
          <div class="brand-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10" />
              <circle cx="12" cy="12" r="4" />
              <line x1="12" y1="2" x2="12" y2="6" />
              <line x1="12" y1="18" x2="12" y2="22" />
              <line x1="2" y1="12" x2="6" y2="12" />
              <line x1="18" y1="12" x2="22" y2="12" />
            </svg>
          </div>
          <div class="brand-text">
            <span class="brand-title">scMarkerMiner</span>
            <span class="brand-sub">scRNA-seq Marker Explorer</span>
          </div>
        </router-link>

        <nav class="header-nav">
          <router-link to="/" class="nav-link" :class="{ active: $route.path === '/' }">
            <el-icon><DataAnalysis /></el-icon>
            <span>Dashboard</span>
          </router-link>
          <router-link to="/search" class="nav-link" :class="{ active: $route.path.startsWith('/search') || $route.path.startsWith('/marker') }">
            <el-icon><Search /></el-icon>
            <span>Marker Search</span>
          </router-link>
        </nav>
      </div>
    </header>

    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { DataAnalysis, Search } from '@element-plus/icons-vue'
</script>

<style scoped>
.app-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  background: linear-gradient(135deg, var(--header-bg) 0%, var(--header-bg-dark) 100%);
  color: #fff;
  position: sticky;
  top: 0;
  z-index: 1000;
  box-shadow: 0 2px 12px rgba(0,0,0,.15);
}

.header-inner {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 40px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #fff;
  text-decoration: none;
}

.brand-icon {
  width: 38px;
  height: 38px;
  background: rgba(255,255,255,.12);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #7eb8f7;
}

.brand-title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.3px;
}

.brand-sub {
  display: block;
  font-size: 11px;
  color: rgba(255,255,255,.55);
  margin-top: 1px;
}

.header-nav {
  display: flex;
  gap: 4px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border-radius: 6px;
  color: rgba(255,255,255,.7);
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  transition: all .2s;
}

.nav-link:hover {
  color: #fff;
  background: rgba(255,255,255,.1);
}

.nav-link.active {
  color: #fff;
  background: rgba(255,255,255,.15);
}

.app-main {
  flex: 1;
  overflow-y: auto;
}

@media (max-width: 1200px) {
  .header-inner { padding: 0 20px; }
}
</style>
