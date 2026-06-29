<template>
  <main class="page-shell">
    <header class="top-bar">
      <div>
        <h1>N型切换</h1>
        <p>{{ latestDateLabel }} · {{ total }} 条</p>
      </div>
      <button class="primary-action" :disabled="exporting" @click="exportXlsx">
        {{ exporting ? "导出中" : "导出 XLSX" }}
      </button>
    </header>

    <section class="filter-row">
      <div class="segmented" aria-label="recent days">
        <button :class="{ active: filters.days === 3 }" @click="setDays(3)">近3日</button>
        <button :class="{ active: filters.days === 10 }" @click="setDays(10)">近10日</button>
      </div>

      <label class="field">
        <span>日期</span>
        <select v-model="filters.trade_date" @change="loadTransitions">
          <option value="">全部</option>
          <option v-for="date in availableDates" :key="date" :value="date">{{ date }}</option>
        </select>
      </label>

      <label class="field">
        <span>切换</span>
        <select v-model="filters.transition" @change="loadTransitions">
          <option value="all">全部</option>
          <option value="positive_to_reverse">正N → 反N</option>
          <option value="reverse_to_positive">反N → 正N</option>
        </select>
      </label>

      <label class="field search-field">
        <span>查询</span>
        <input v-model.trim="filters.q" placeholder="代码 / 拼音" @input="onSearchInput" />
      </label>
    </section>

    <section class="metric-grid">
      <div class="metric">
        <span>正N转反N</span>
        <strong>{{ transitionCounts.positive_to_reverse || 0 }}</strong>
      </div>
      <div class="metric">
        <span>反N转正N</span>
        <strong>{{ transitionCounts.reverse_to_positive || 0 }}</strong>
      </div>
      <div class="metric">
        <span>SVG</span>
        <strong>{{ summary.transition_summary?.svg_rows || 0 }}</strong>
      </div>
      <div class="metric">
        <span>更新</span>
        <strong>{{ generatedAt }}</strong>
      </div>
    </section>

    <section class="workspace">
      <div class="table-panel">
        <div class="table-scroller">
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>股票</th>
                <th>切换</th>
                <th>当前</th>
                <th>前次</th>
                <th class="number">收盘</th>
                <th class="number">成交量</th>
                <th class="number">拐点</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in items"
                :key="`${item.trade_date}-${item.ts_code}-${item.n_transition}`"
                :class="{ selected: selectedKey(item) === selectedKey(selected) }"
                @click="selectItem(item)"
              >
                <td>{{ item.trade_date }}</td>
                <td>
                  <strong>{{ item.display_name }}</strong>
                  <small>{{ item.ts_code }}</small>
                </td>
                <td>
                  <span class="pill" :class="transitionClass(item.n_transition)">
                    {{ transitionLabel(item.n_transition) }}
                  </span>
                </td>
                <td>{{ signalLabel(item.n_signal_name) }}</td>
                <td>
                  <span>{{ signalLabel(item.n_prev_signal_name) }}</span>
                  <small>{{ item.n_prev_trade_date }}</small>
                </td>
                <td class="number">{{ formatNumber(item.close, 2) }}</td>
                <td class="number">{{ formatCompact(item.vol) }}</td>
                <td class="number">{{ item.n_pivot_count ?? "" }}</td>
              </tr>
              <tr v-if="!loading && items.length === 0">
                <td colspan="8" class="empty">暂无数据</td>
              </tr>
              <tr v-if="loading">
                <td colspan="8" class="empty">加载中</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <aside class="preview-panel">
        <div class="preview-head">
          <div>
            <h2>{{ selected?.display_name || "SVG" }}</h2>
            <p>{{ selected?.trade_date || "" }} {{ transitionLabel(selected?.n_transition) }}</p>
          </div>
          <a v-if="selected?.svg_url" :href="selected.svg_url" target="_blank" rel="noreferrer">打开</a>
        </div>
        <div class="svg-frame">
          <img
            v-if="selected?.svg_url"
            :src="selected.svg_url"
            :alt="selected.display_name"
            class="zoomable-svg"
            @click="openImageZoom"
          />
          <div v-else class="empty preview-empty">未选择图形</div>
        </div>
      </aside>
    </section>

    <div v-if="imageZoomOpen && selected?.svg_url" class="lightbox" @click="closeImageZoom">
      <button class="lightbox-close" type="button" @click.stop="closeImageZoom">关闭</button>
      <img
        :src="selected.svg_url"
        :alt="selected.display_name"
        class="lightbox-image"
        @click.stop
      />
    </div>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";

const apiBase = import.meta.env.VITE_API_BASE || "";
const filters = reactive({
  days: 3,
  trade_date: "",
  transition: "all",
  q: ""
});
const summary = ref({});
const items = ref([]);
const total = ref(0);
const selected = ref(null);
const loading = ref(false);
const exporting = ref(false);
const imageZoomOpen = ref(false);
let searchTimer = 0;

const availableDates = computed(() => summary.value.available_dates || []);
const transitionCounts = computed(() => summary.value.transition_counts || {});
const generatedAt = computed(() => {
  const value = summary.value.transition_summary?.generated_at;
  return value ? value.slice(5, 16) : "--";
});
const latestDateLabel = computed(() => {
  const dates = availableDates.value;
  if (!dates.length) return "暂无日期";
  return `最新 ${dates[dates.length - 1]}`;
});

function buildParams(includePaging = true) {
  const params = new URLSearchParams();
  params.set("days", filters.days);
  if (filters.trade_date) params.set("trade_date", filters.trade_date);
  if (filters.transition) params.set("transition", filters.transition);
  if (filters.q) params.set("q", filters.q);
  if (includePaging) {
    params.set("limit", "500");
    params.set("offset", "0");
  }
  return params;
}

async function loadSummary() {
  const response = await fetch(`${apiBase}/api/summary`);
  summary.value = await response.json();
}

async function loadTransitions() {
  loading.value = true;
  try {
    const response = await fetch(`${apiBase}/api/transitions?${buildParams()}`);
    const payload = await response.json();
    const prevSelectedKey = selectedKey(selected.value);
    items.value = payload.items || [];
    total.value = payload.total || 0;
    selected.value = items.value.find((item) => selectedKey(item) === prevSelectedKey) || items.value[0] || null;
    if (!selected.value) {
      imageZoomOpen.value = false;
    }
  } finally {
    loading.value = false;
  }
}

function onSearchInput() {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(loadTransitions, 250);
}

function setDays(days) {
  filters.days = days;
  filters.trade_date = "";
  loadTransitions();
}

function selectItem(item) {
  selected.value = item;
}

function moveSelection(step) {
  if (!items.value.length) return;
  const currentKey = selectedKey(selected.value);
  const currentIndex = items.value.findIndex((item) => selectedKey(item) === currentKey);
  if (currentIndex < 0) {
    selected.value = items.value[0];
    return;
  }
  const nextIndex = Math.max(0, Math.min(items.value.length - 1, currentIndex + step));
  selected.value = items.value[nextIndex];
}

function isTypingTarget(target) {
  if (!target || !(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return target.isContentEditable || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function onGlobalKeydown(event) {
  if (isTypingTarget(event.target)) return;

  if (event.key === "Escape" && imageZoomOpen.value) {
    imageZoomOpen.value = false;
    return;
  }

  if (event.key === "ArrowUp") {
    event.preventDefault();
    moveSelection(-1);
    return;
  }

  if (event.key === "ArrowDown") {
    event.preventDefault();
    moveSelection(1);
  }
}

function openImageZoom() {
  if (!selected.value?.svg_url) return;
  imageZoomOpen.value = true;
}

function closeImageZoom() {
  imageZoomOpen.value = false;
}

async function exportXlsx() {
  exporting.value = true;
  try {
    const response = await fetch(`${apiBase}/api/export.xlsx?${buildParams(false)}`);
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `n_pattern_${Date.now()}.xlsx`;
    link.click();
    window.URL.revokeObjectURL(url);
  } finally {
    exporting.value = false;
  }
}

function selectedKey(item) {
  if (!item) return "";
  return `${item.trade_date}-${item.ts_code}-${item.n_transition}`;
}

function transitionLabel(value) {
  if (value === "positive_to_reverse") return "正N → 反N";
  if (value === "reverse_to_positive") return "反N → 正N";
  return value || "";
}

function transitionClass(value) {
  return value === "reverse_to_positive" ? "positive" : "reverse";
}

function signalLabel(value) {
  if (value === "positive_n") return "正N";
  if (value === "reverse_n") return "反N";
  if (value === "none") return "无";
  return value || "";
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : value;
}

function formatCompact(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  if (number >= 100000000) return `${(number / 100000000).toFixed(2)}亿`;
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return String(Math.round(number));
}

onMounted(async () => {
  window.addEventListener("keydown", onGlobalKeydown);
  await loadSummary();
  await loadTransitions();
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onGlobalKeydown);
});
</script>
