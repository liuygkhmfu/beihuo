const state = {
  dashboard: null,
  settings: null,
  schedule: [],
  activePage: "workbench",
  activeView: "shipping",
  charts: {},
  currentDetail: null,
  shipmentData: null,
  purchasePlan: null,
  editingShipment: null,
  editingAlias: null,
  productStatusSelection: new Set(),
  manualScenarioNodes: [],
  manualScenarioResult: null,
  scenarioDirty: false,
  scenarioRecalcTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function icons() {
  if (window.lucide) window.lucide.createIcons();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatQty(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(number);
}

function formatDecimal(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(digits).replace(/\.0$/, "");
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(`${value}T00:00:00`);
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

function addDays(value, days) {
  if (!value) return "";
  const date = new Date(`${value}T00:00:00`);
  date.setDate(date.getDate() + Math.ceil(Number(days || 0)));
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

function showToast(message, error = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("is-error", error);
  toast.classList.add("is-visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("is-visible"), 2800);
}

function showLoading(title, text) {
  $("#loadingTitle").textContent = title;
  $("#loadingText").textContent = text;
  $("#loadingOverlay").hidden = false;
}

function hideLoading() {
  $("#loadingOverlay").hidden = true;
}

async function api(url, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(url, {
    cache: "no-store",
    headers: isFormData
      ? (options.headers || {})
      : { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok || (payload && payload.ok === false)) {
    const error = new Error(payload?.error || `请求失败：${response.status}`);
    error.payload = payload;
    throw error;
  }
  return payload;
}

function riskInfo(code) {
  return {
    critical: ["常规渠道前断货", "risk-critical"],
    urgent: ["需加急渠道", "risk-urgent"],
    attention: ["需常规渠道", "risk-attention"],
    healthy: ["健康", "risk-healthy"],
    no_sales: ["无有效销量", "risk-no_sales"],
    excluded: ["不参与补货", "risk-no_sales"],
  }[code] || ["待判断", "risk-no_sales"];
}

function statusText(code) {
  return {
    pending: "待复核",
    reviewed: "已复核",
    executed: "已执行",
  }[code] || "待复核";
}

function riskBadge(item) {
  const [label, className] = riskInfo(item.risk);
  return `<span class="risk-badge ${className}">${label}</span>`;
}

function statusBadge(item) {
  return `<span class="status-badge status-${escapeHtml(item.review_status)}">${statusText(item.review_status)}</span>`;
}

function planningStatusInfo(code) {
  return {
    active: ["正常补货", "planning-status-active"],
    clearance: ["清仓", "planning-status-clearance"],
    delisted: ["下架", "planning-status-delisted"],
  }[code] || ["正常补货", "planning-status-active"];
}

function planningStatusBadge(item) {
  const [label, className] = planningStatusInfo(item.planning_status);
  return `<span class="planning-status-badge ${className}">${label}</span>`;
}

function productIdentity(item) {
  return item.product_group_id || `${item.store_id}|${item.canonical_msku || item.msku}`;
}

function productMemberMskus(item) {
  return item.member_mskus?.length ? item.member_mskus : [item.msku];
}

function productMskuSummary(item) {
  const members = productMemberMskus(item);
  return item.is_grouped
    ? `执行 ${item.execution_msku || item.msku} · 合并 ${members.join(" / ")}`
    : item.msku;
}

function formatDateTime(value) {
  return value ? String(value).replace("T", " ") : "—";
}

function sourceStamp(snapshot) {
  const time = snapshot.collected_at?.replace("T", " ") || "—";
  const rawNote = Number(snapshot.raw_product_count || 0) > Number(snapshot.product_count || 0)
    ? ` · ${snapshot.raw_product_count}条原始MSKU`
    : "";
  $("#sourceStamp").textContent = `${snapshot.source} · ${time} · ${snapshot.product_count}个商品组${rawNote}`;
}

function roundPurchaseDaily(value) {
  return Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
}

function recalculatePurchaseItem(item) {
  item.adopted_daily = roundPurchaseDaily(
    item.daily_override === null || item.daily_override === undefined
      ? item.dynamic_daily
      : item.daily_override,
  );
  item.system_qty = Math.ceil(Math.max(
    0,
    item.adopted_daily * (Number(item.remaining_days || 0) + Number(item.extra_days || 0)),
  ));
  item.final_qty = item.final_override === null || item.final_override === undefined
    ? item.system_qty
    : Math.ceil(Math.max(0, Number(item.final_override || 0)));
  item.has_manual_adjustment = item.daily_override !== null
    || Number(item.extra_days || 0) > 0
    || item.final_override !== null
    || Boolean(item.note);
}

function updatePurchasePlanMonth(completedMonth) {
  if (!state.purchasePlan) return;
  state.purchasePlan.completed_month = Number(completedMonth);
  let remainingDays = 0;
  state.purchasePlan.month_plan.forEach((month) => {
    month.is_completed = Number(completedMonth) > 0 && Number(month.month) <= Number(completedMonth);
    if (!month.is_completed) remainingDays += Number(month.equivalent_days);
  });
  state.purchasePlan.remaining_equivalent_days = Number(remainingDays.toFixed(4));
  state.purchasePlan.items.forEach((item) => {
    item.remaining_days = state.purchasePlan.remaining_equivalent_days;
    recalculatePurchaseItem(item);
  });
}

async function loadPurchasePlan(asOf = "") {
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  const payload = await api(`/api/purchase-plan${query}`);
  state.purchasePlan = payload.data;
  renderPurchasePlan();
}

function purchaseProductCell(item) {
  const image = item.image_url
    ? `<img class="product-thumb" src="${escapeHtml(item.image_url)}" alt="">`
    : "";
  const stores = item.stores?.length ? item.stores.join("、") : "领星";
  return `<div class="product-cell">${image}<div><strong>${escapeHtml(item.product_name || "未命名商品")}</strong><small>${escapeHtml(item.sku)} · ${escapeHtml(stores)}</small></div></div>`;
}

function purchaseFilteredItems() {
  const search = ($("#purchaseSearchInput")?.value || "").trim().toLowerCase();
  if (!state.purchasePlan) return [];
  return state.purchasePlan.items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => !search || `${item.sku} ${item.product_name}`.toLowerCase().includes(search));
}

function purchaseInput(value, field, index, options = {}) {
  const step = options.step || "0.01";
  const min = options.min ?? "0";
  return `<input class="purchase-number-input" type="number" min="${min}" step="${step}" value="${escapeHtml(value)}" data-purchase-field="${field}" data-index="${index}">`;
}

function renderPurchaseTable() {
  if (!state.purchasePlan) return;
  const rows = purchaseFilteredItems();
  $("#purchaseTableCount").textContent = `${rows.length}个SKU`;
  $("#purchaseTableBody").innerHTML = rows.length
    ? rows.map(({ item, index }) => `
      <tr class="${item.has_manual_adjustment ? "purchase-row-adjusted" : ""}">
        <td>${purchaseProductCell(item)}</td>
        <td class="number"><strong>${formatDecimal(item.dynamic_daily, 2)}</strong><small class="block-muted">系统预测</small></td>
        <td>
          <div class="purchase-input-stack">
            ${purchaseInput(item.adopted_daily, "daily", index)}
            <button class="link-button purchase-reset-button" type="button" data-purchase-reset="daily" data-index="${index}" ${item.daily_override === null ? "disabled" : ""}>跟随系统</button>
          </div>
        </td>
        <td class="number"><strong>${formatDecimal(item.remaining_days, 4)}天</strong></td>
        <td>${purchaseInput(item.extra_days, "extra", index, { step: "0.5" })}</td>
        <td class="number quantity-strong" data-purchase-value="system" data-index="${index}">${formatQty(item.system_qty)}</td>
        <td>
          <div class="purchase-input-stack">
            ${purchaseInput(item.final_qty, "final", index, { step: "1" })}
            <button class="link-button purchase-reset-button" type="button" data-purchase-reset="final" data-index="${index}" ${item.final_override === null ? "disabled" : ""}>跟随公式</button>
          </div>
        </td>
        <td><input class="purchase-note-input" type="text" value="${escapeHtml(item.note || "")}" placeholder="达人、新品等原因" data-purchase-field="note" data-index="${index}"></td>
      </tr>`).join("")
    : `<tr><td class="empty-row" colspan="8">没有符合条件的商品</td></tr>`;
}

function renderPurchaseSummary() {
  if (!state.purchasePlan) return;
  const plan = state.purchasePlan;
  $("#purchaseDaysMetric").textContent = `${formatDecimal(plan.remaining_equivalent_days, 4)}天`;
  $("#purchaseDailyMetric").textContent = `${formatDecimal(plan.items.reduce((sum, item) => sum + Number(item.dynamic_daily || 0), 0), 2)}件`;
  $("#purchaseSystemMetric").textContent = `${formatQty(plan.items.reduce((sum, item) => sum + Number(item.system_qty || 0), 0))}件`;
  const finalTotal = plan.items.reduce((sum, item) => sum + Number(item.final_qty || 0), 0);
  const positiveCount = plan.items.filter((item) => Number(item.final_qty || 0) > 0).length;
  $("#purchaseFinalMetric").textContent = `${formatQty(finalTotal)}件`;
  $("#purchaseFinalHint").textContent = `${positiveCount}个SKU将进入导出表`;
}

function renderPurchasePlan() {
  if (!state.purchasePlan) return;
  const plan = state.purchasePlan;
  $("#purchaseCompletedMonth").value = String(plan.completed_month);
  renderPurchaseSummary();
  $("#purchaseFormulaNote").textContent = plan.calculation_note;
  $("#purchaseMonthPlan").innerHTML = plan.month_plan.map((month) => `
    <article class="purchase-month ${month.is_completed ? "is-completed" : ""}">
      <span>${escapeHtml(month.label)}</span>
      <strong>${formatDecimal(month.multiplier, 3)}倍</strong>
      <small>${formatDecimal(month.equivalent_days, 3)}等效天${month.is_completed ? " · 已扣除" : ""}</small>
    </article>`).join("");
  renderPurchaseTable();
}

function updatePurchaseInput(target) {
  if (!state.purchasePlan) return;
  const item = state.purchasePlan.items[Number(target.dataset.index)];
  if (!item) return;
  const field = target.dataset.purchaseField;
  if (field === "daily") item.daily_override = roundPurchaseDaily(Math.max(0, Number(target.value || 0)));
  if (field === "extra") item.extra_days = Math.max(0, Number(target.value || 0));
  if (field === "final") item.final_override = Math.max(0, Number(target.value || 0));
  if (field === "note") item.note = target.value.trim();
  recalculatePurchaseItem(item);
  const row = target.closest("tr");
  if (row) {
    row.classList.toggle("purchase-row-adjusted", item.has_manual_adjustment);
    const systemCell = row.querySelector('[data-purchase-value="system"]');
    if (systemCell) systemCell.textContent = formatQty(item.system_qty);
    const finalInput = row.querySelector('[data-purchase-field="final"]');
    if (finalInput && field !== "final") finalInput.value = item.final_qty;
    const dailyReset = row.querySelector('[data-purchase-reset="daily"]');
    const finalReset = row.querySelector('[data-purchase-reset="final"]');
    if (dailyReset) dailyReset.disabled = item.daily_override === null;
    if (finalReset) finalReset.disabled = item.final_override === null;
  }
  renderPurchaseSummary();
}

function resetPurchaseInput(button) {
  if (!state.purchasePlan) return;
  const item = state.purchasePlan.items[Number(button.dataset.index)];
  if (!item) return;
  if (button.dataset.purchaseReset === "daily") item.daily_override = null;
  if (button.dataset.purchaseReset === "final") item.final_override = null;
  recalculatePurchaseItem(item);
  renderPurchasePlan();
}

async function savePurchasePlan(quiet = false) {
  if (!state.purchasePlan) throw new Error("备货计划尚未加载");
  const plan = state.purchasePlan;
  const payload = await api("/api/purchase-plan", {
    method: "POST",
    body: JSON.stringify({
      as_of: $("#asOfInput").value || plan.as_of,
      season_year: plan.season_year,
      completed_month: plan.completed_month,
      items: plan.items.map((item) => ({
        sku_key: item.sku_key,
        adopted_daily: item.daily_override,
        extra_days: Number(item.extra_days || 0),
        final_qty: item.final_override,
        note: item.note || "",
      })),
    }),
  });
  state.purchasePlan = payload.data;
  renderPurchasePlan();
  if (!quiet) showToast("备货调整已保存");
}

async function exportPurchasePlan() {
  try {
    await savePurchasePlan(true);
    const asOf = $("#asOfInput").value || state.purchasePlan.as_of;
    window.location.href = `/api/purchase-plan/export?as_of=${encodeURIComponent(asOf)}`;
    showToast("正在导出TK备货表");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function loadSettings() {
  const payload = await api("/api/settings");
  state.settings = payload.settings;
  state.schedule = payload.schedule;
  populateSettings();
  renderSchedule();
}

async function loadDashboard(asOf = "") {
  try {
    const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
    const payload = await api(`/api/dashboard${query}`);
    state.dashboard = payload.data;
    state.settings = payload.data.settings;
    state.schedule = payload.data.schedule;
    $("#emptyState").hidden = true;
    $("#dashboardContent").hidden = false;
    $("#asOfInput").value = payload.data.as_of;
    sourceStamp(payload.data.snapshot);
    renderDashboard();
    await loadShipments(payload.data.as_of);
    populateSettings();
    renderSchedule();
    state.purchasePlan = null;
    if (state.activePage === "purchase") await loadPurchasePlan(payload.data.as_of);
  } catch (error) {
    if (error.payload?.needs_pull) {
      state.dashboard = null;
      $("#emptyState").hidden = false;
      $("#dashboardContent").hidden = true;
      $("#sourceStamp").textContent = "尚未拉取领星数据";
      await loadSettings();
      return;
    }
    showToast(error.message, true);
    throw error;
  }
}

const CHANNEL_UI = [
  { key: "express", label: "快递", setting: "express_channel_enabled" },
  { key: "air", label: "空派", setting: "air_channel_enabled" },
  { key: "quick", label: "快船", setting: "quick_channel_enabled" },
  { key: "truck", label: "普船卡派", setting: "truck_channel_enabled" },
  { key: "slow", label: "COSCO慢船", setting: "slow_channel_enabled" },
];

function settingChannelEnabled(key) {
  const definition = CHANNEL_UI.find((item) => item.key === key);
  return definition ? state.settings?.[definition.setting] !== false : false;
}

function itemChannelEnabled(item, key) {
  return item.channel_plans?.find((plan) => plan.key === key)?.enabled !== false;
}

function renderDashboard() {
  const { summary, shipment_summary: shipmentSummary, schedule_context: context, snapshot } = state.dashboard;
  const expressEnabled = settingChannelEnabled("express");
  const airChannelEnabled = settingChannelEnabled("air");
  const airEnabled = airChannelEnabled;
  const enabledRegularLabels = CHANNEL_UI
    .filter((item) => !["express", "air"].includes(item.key) && settingChannelEnabled(item.key))
    .map((item) => item.label);
  const timingMode = state.settings.timing_mode === "fixed" ? "固定频率" : "精准船期";
  const representativeProduct = state.dashboard.products[0];
  const representativePlans = representativeProduct?.channel_plans || [];
  const quickPlan = representativePlans.find((plan) => plan.enabled && !["express", "air"].includes(plan.key));
  $("#shipMetric").textContent = formatQty(summary.ship_total_qty);
  $("#shipMetricHint").textContent = `${summary.ship_sku_count} 个商品`;
  const urgentEnabled = expressEnabled || airEnabled;
  $("#airMetricCard").classList.toggle("metric-danger", urgentEnabled && summary.air_warning_count > 0);
  $("#airMetricLabel").textContent = "加急渠道建议";
  $("#airMetric").textContent = urgentEnabled ? formatQty(summary.urgent_total_qty) : "已停用";
  $("#airMetricHint").textContent = urgentEnabled
    ? `快递${formatQty(summary.express_total_qty)}件 / 空派${formatQty(summary.air_total_qty)}件`
    : `当前使用：${enabledRegularLabels.join("、")}`;
  $("#criticalRiskOption").hidden = false;
  $("#coverageHint").textContent = `按动态日均计算；${timingMode}${quickPlan ? `，${quickPlan.label}最终预计${formatDate(quickPlan.arrival_date)}到货` : ""}`;
  const urgentLabels = [
    ...(expressEnabled ? ["快递"] : []),
    ...(airEnabled ? ["空派"] : []),
  ];
  $("#channelHint").textContent = `${urgentLabels.length ? `${urgentLabels.join("、")}桥接紧急缺口；` : ""}${enabledRegularLabels.join("、")}按最终预计到货日依次接力`;
  $("#buyMetric").textContent = formatQty(summary.buy_total_qty);
  $("#buyMetricHint").textContent = `${summary.buy_sku_count} 个商品待核对`;
  $("#dataMetric").textContent = summary.data_issue_count + Number(shipmentSummary?.overdue_count || 0);
  $("#dataMetric").nextElementSibling.textContent = shipmentSummary?.overdue_count
    ? `含 ${shipmentSummary.overdue_count} 个逾期未接收IBR`
    : "商品数据与到货台账均无阻断异常";

  $("#weekRibbon").innerHTML = [
    ["上一周一计划", context.previous, ""],
    ["本次发货计划", context.current, "is-current"],
    ["下次买货测算", context.next, "is-next"],
  ].map(([title, item, className]) => {
    const seasonalDays = Number(item.seasonal_coverage_days);
    const seasonalSafety = Number(representativeProduct?.safety_buffer_days || 0);
    const seasonalFrequency = Number(representativeProduct?.dispatch_interval_days || 0);
    const totalDays = seasonalDays
      + seasonalSafety
      + seasonalFrequency;
    return `
    <div class="week-block ${className}">
      <span>${title}</span>
      <strong>${formatDecimal(totalDays, 4)} 天</strong>
      <small>基础${formatDecimal(seasonalDays, 4)} + ${escapeHtml(representativeProduct?.seasonal_channel_label || "旺季渠道")}安全${formatDecimal(seasonalSafety)} + 频率${formatDecimal(seasonalFrequency)} · ${formatDate(item.week_date)}</small>
    </div>
  `}).join("");

  const storeSelect = $("#storeFilter");
  const selectedStore = storeSelect.value;
  storeSelect.innerHTML = `<option value="">全部店铺</option>${snapshot.stores.map((store) =>
    `<option value="${escapeHtml(store.store_id)}">${escapeHtml(store.store_name)}</option>`
  ).join("")}`;
  storeSelect.value = selectedStore;
  const importStore = $("#arrivalImportStore");
  const selectedImportStore = importStore.value;
  importStore.innerHTML = `<option value="">自动识别</option>${snapshot.stores.map((store) =>
    `<option value="${escapeHtml(store.store_id)}">${escapeHtml(store.store_name)}</option>`
  ).join("")}`;
  importStore.value = selectedImportStore;

  renderCoverageChart();
  renderChannelChart();
  renderTable();
  renderProductStatusPage();
  icons();
}

function filteredProductStatusItems() {
  if (!state.dashboard) return [];
  const storeId = $("#productStatusStoreFilter")?.value || "";
  const status = $("#productStatusFilter")?.value || "";
  const query = ($("#productStatusSearchInput")?.value || "").trim().toLowerCase();
  return state.dashboard.products.filter((item) => {
    if (storeId && item.store_id !== storeId) return false;
    if (status && item.planning_status !== status) return false;
    if (query) {
      const haystack = [
        item.product_name,
        item.msku,
        ...(item.member_mskus || []),
        item.sku,
        item.store_name,
      ].join(" ").toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

function updateProductStatusSelectionState(visibleItems = filteredProductStatusItems()) {
  const validKeys = new Set(
    (state.dashboard?.products || []).map((item) => productIdentity(item)),
  );
  state.productStatusSelection.forEach((key) => {
    if (!validKeys.has(key)) state.productStatusSelection.delete(key);
  });
  const selectedCount = state.productStatusSelection.size;
  if ($("#productStatusSelectedMetric")) {
    $("#productStatusSelectedMetric").textContent = formatQty(selectedCount);
  }
  const selectAll = $("#productStatusSelectAll");
  if (selectAll) {
    const visibleKeys = visibleItems.map((item) => productIdentity(item));
    const selectedVisible = visibleKeys.filter(
      (key) => state.productStatusSelection.has(key),
    ).length;
    selectAll.checked = visibleKeys.length > 0
      && selectedVisible === visibleKeys.length;
    selectAll.indeterminate = selectedVisible > 0
      && selectedVisible < visibleKeys.length;
  }
}

function renderProductStatusPage() {
  const tbody = $("#productStatusTableBody");
  if (!tbody) return;
  const products = state.dashboard?.products || [];
  const counts = products.reduce(
    (result, item) => {
      result[item.planning_status] = (result[item.planning_status] || 0) + 1;
      return result;
    },
    { active: 0, clearance: 0, delisted: 0 },
  );
  $("#productStatusActiveMetric").textContent = formatQty(counts.active);
  $("#productStatusClearanceMetric").textContent = formatQty(counts.clearance);
  $("#productStatusDelistedMetric").textContent = formatQty(counts.delisted);

  const storeFilter = $("#productStatusStoreFilter");
  const selectedStore = storeFilter.value;
  const stores = state.dashboard?.snapshot?.stores || [];
  storeFilter.innerHTML = `<option value="">全部店铺</option>${stores.map((store) =>
    `<option value="${escapeHtml(store.store_id)}">${escapeHtml(store.store_name)}</option>`
  ).join("")}`;
  storeFilter.value = stores.some((store) => store.store_id === selectedStore)
    ? selectedStore
    : "";

  const visibleItems = filteredProductStatusItems();
  $("#productStatusTableCount").textContent = `${visibleItems.length} 个商品`;
  tbody.innerHTML = visibleItems.length
    ? visibleItems.map((item) => {
      const key = productIdentity(item);
      const image = item.image_url
        ? `<img class="product-thumb" src="${escapeHtml(item.image_url)}" alt="">`
        : '<span class="product-thumb product-thumb-empty"></span>';
      return `
        <tr class="${item.is_planning_excluded ? "is-excluded-row" : ""}">
          <td class="selection-column">
            <input class="product-status-checkbox" type="checkbox"
              data-product-key="${escapeHtml(key)}"
              aria-label="勾选${escapeHtml(item.product_name)}"
              ${state.productStatusSelection.has(key) ? "checked" : ""}>
          </td>
          <td>
            <div class="product-cell">${image}<div>
              <strong title="${escapeHtml(item.product_name)}">${escapeHtml(item.product_name)}</strong>
              <small>${planningStatusBadge(item)}</small>
            </div></div>
          </td>
          <td>${escapeHtml(item.store_name)}</td>
          <td><strong>${escapeHtml(item.execution_msku || item.msku)}</strong><small class="block-muted">${escapeHtml(item.is_grouped ? `合并：${productMemberMskus(item).join(" / ")}` : item.sku || "—")}</small></td>
          <td class="number">${formatDecimal(item.dynamic_daily, 2)}件</td>
          <td class="number">${formatQty(item.fbt_sellable)} / ${formatQty(item.fbt_in_transit)}</td>
          <td>
            <select class="table-status-select product-status-row-select"
              data-store-id="${escapeHtml(item.store_id)}"
              data-msku="${escapeHtml(item.msku)}"
              aria-label="${escapeHtml(item.product_name)}的产品状态">
              <option value="active" ${item.planning_status === "active" ? "selected" : ""}>正常补货</option>
              <option value="clearance" ${item.planning_status === "clearance" ? "selected" : ""}>清仓</option>
              <option value="delisted" ${item.planning_status === "delisted" ? "selected" : ""}>下架</option>
            </select>
          </td>
          <td>${formatDateTime(item.planning_status_updated_at)}</td>
        </tr>`;
    }).join("")
    : '<tr><td class="empty-row" colspan="8">当前筛选条件下没有商品</td></tr>';
  updateProductStatusSelectionState(visibleItems);
  icons();
}

async function saveProductStatusItems(items, successMessage) {
  if (!items.length) {
    showToast("请先选择需要标记的商品", true);
    return;
  }
  showLoading("正在保存产品状态", `正在更新 ${items.length} 个商品`);
  try {
    await api("/api/product-status", {
      method: "POST",
      body: JSON.stringify({ items }),
    });
    state.productStatusSelection.clear();
    await loadDashboard($("#asOfInput").value);
    showToast(successMessage || `已更新 ${items.length} 个商品`);
  } catch (error) {
    showToast(error.message, true);
    renderProductStatusPage();
  } finally {
    hideLoading();
  }
}

function applyProductStatusBatch() {
  const status = $("#productStatusBatchSelect").value;
  const items = (state.dashboard?.products || [])
    .filter((item) => state.productStatusSelection.has(productIdentity(item)))
    .map((item) => ({
      store_id: item.store_id,
      msku: item.msku,
      status,
    }));
  const [label] = planningStatusInfo(status);
  saveProductStatusItems(items, `已将 ${items.length} 个商品标记为${label}`);
}

async function loadShipments(asOf = "") {
  try {
    const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
    const payload = await api(`/api/shipments${query}`);
    state.shipmentData = payload.data;
    renderShipments();
  } catch (error) {
    state.shipmentData = null;
    if (state.activePage === "shipments") showToast(error.message, true);
  }
}

function shipmentStatusBadge(item) {
  const labels = {
    overdue: ["逾期未接收", "risk-critical"],
    awaiting_receive: ["已签收待FBT接收", "risk-urgent"],
    in_transit: ["运输中", "risk-attention"],
    manual_pending: ["待领星同步", "risk-no_sales"],
    pending: ["待发货", "risk-no_sales"],
    empty: ["无发货量", "risk-no_sales"],
    received: ["已全部接收", "risk-healthy"],
    archived: ["历史归档", "risk-no_sales"],
  };
  const [label, className] = labels[item.status] || [item.status_name || "待判断", "risk-no_sales"];
  return `<span class="risk-badge ${className}">${label}</span>`;
}

function filteredShipments() {
  if (!state.shipmentData) return [];
  const status = $("#shipmentStatusFilter").value;
  const search = $("#shipmentSearchInput").value.trim().toLowerCase();
  return state.shipmentData.shipments.filter((item) => {
    if (
      status === "active"
      && (item.is_received || item.is_archived || Number(item.remaining_qty || 0) <= 0)
    ) return false;
    if (status && status !== "active" && item.status !== status) return false;
    if (!search) return true;
    const productText = item.items.map((row) => `${row.msku} ${row.sku} ${row.product_name}`).join(" ");
    const haystack = `${item.cargo_code} ${item.shipping_list_code} ${item.store_name} ${item.tracking_number} ${productText}`.toLowerCase();
    return haystack.includes(search);
  });
}

function shipmentProductsCell(item) {
  const visible = item.items.slice(0, 2).map((row) =>
    `<strong>${escapeHtml(row.msku)}</strong><small>${escapeHtml(row.product_name)}</small>`
  ).join("");
  const more = item.items.length > 2 ? `<small>另有 ${item.items.length - 2} 个MSKU</small>` : "";
  return `<div class="shipment-products">${visible || "<span class='muted'>无商品明细</span>"}${more}</div>`;
}

function renderShipments() {
  if (!state.shipmentData) return;
  const { summary } = state.shipmentData;
  $("#shipmentActiveMetric").textContent = formatQty(summary.active_count);
  $("#shipmentQtyMetric").textContent = formatQty(summary.active_remaining_qty);
  $("#shipmentAwaitingMetric").textContent = formatQty(summary.awaiting_receive_qty);
  $("#shipmentOverdueMetric").textContent = formatQty(summary.overdue_count);
  $("#shipmentEtaMetric").textContent = formatQty(summary.missing_eta_count);
  $("#shipmentTrackingMetric").textContent = formatQty(summary.missing_tracking_count);
  const tracking = state.shipmentData.arrival_tracking || {};
  const matchIssues = Number(tracking.unmatched_count || 0) + Number(tracking.conflict_count || 0);
  $("#shipmentMatchMetric").textContent = formatQty(matchIssues);
  $("#shipmentOverdueCard").classList.toggle("metric-danger", summary.overdue_count > 0);
  $("#shipmentMatchCard").classList.toggle("metric-danger", matchIssues > 0);

  const rows = filteredShipments();
  $("#shipmentTableCount").textContent = `${rows.length} 个货件`;
  $("#shipmentTableBody").innerHTML = rows.length ? rows.map((item) => `
    <tr data-cargo="${escapeHtml(item.cargo_code)}">
      <td>${shipmentStatusBadge(item)}</td>
      <td><div class="code-stack"><strong>${escapeHtml(item.cargo_code)}</strong><small>${escapeHtml(item.shipping_list_code || "未关联发货单")}</small></div></td>
      <td>${escapeHtml(item.store_name || "—")}</td>
      <td>${shipmentProductsCell(item)}</td>
      <td class="number shipment-quantity"><strong>${formatQty(item.shipment_qty)}</strong><span>/ ${formatQty(item.signed_qty)}</span><b>/ ${formatQty(item.received_qty)}</b><em>/ ${formatQty(item.remaining_qty)}</em></td>
      <td>${formatDate(item.delivery_time)}</td>
      <td>${item.expected_signed_date ? formatDate(item.expected_signed_date) : `<span class="muted">—</span>`}</td>
      <td>${item.expected_receive_date ? `<strong class="${item.is_overdue ? "quantity-danger" : ""}">${formatDate(item.expected_receive_date)}</strong>` : `<span class="issue-chip">缺入库日</span>`}</td>
      <td><div class="code-stack"><strong>${escapeHtml(item.carrier || item.logistics_provider || "未填写")}</strong><small>${escapeHtml(item.tracking_number || "缺跟踪号")}</small></div></td>
      <td><span class="source-chip ${item.is_api_synced ? "source-api" : "source-manual"}">${item.is_api_synced ? "领星+人工" : "仅人工表"}</span></td>
      <td><button class="button button-secondary shipment-edit-button" type="button" data-cargo="${escapeHtml(item.cargo_code)}"><i data-lucide="pencil"></i><span>补充物流</span></button></td>
    </tr>
  `).join("") : `<tr><td class="empty-row" colspan="11">暂无货件。拉取领星数据或导入到货跟踪表后，货件会沉淀到这里。</td></tr>`;
  renderReconciliation();
  icons();
}

function openShipmentDialog(cargoCode) {
  const shipment = state.shipmentData?.shipments.find((item) => item.cargo_code === cargoCode);
  if (!shipment) return;
  state.editingShipment = shipment;
  $("#shipmentDialogTitle").textContent = shipment.cargo_code;
  $("#shipmentCargoCode").value = shipment.cargo_code;
  $("#shipmentCarrier").value = shipment.carrier || "";
  $("#shipmentTrackingNumber").value = shipment.tracking_number || "";
  $("#shipmentDepartureDate").value = shipment.departure_date || "";
  $("#shipmentPortArrivalDate").value = shipment.port_arrival_date || shipment.expected_signed_date || "";
  $("#shipmentExpectedReceiveDate").value = shipment.expected_receive_date || "";
  $("#shipmentActualSignedDate").value = shipment.actual_signed_date || "";
  $("#shipmentActualReceiveDate").value = shipment.actual_receive_date || "";
  $("#shipmentNote").value = shipment.manual_note || "";
  $("#shipmentDialog").showModal();
  icons();
}

async function saveShipmentOverride() {
  const cargoCode = $("#shipmentCargoCode").value;
  try {
    await api("/api/shipment-override", {
      method: "POST",
      body: JSON.stringify({
        cargo_code: cargoCode,
        carrier: $("#shipmentCarrier").value,
        tracking_number: $("#shipmentTrackingNumber").value.trim(),
        departure_date: $("#shipmentDepartureDate").value,
        port_arrival_date: $("#shipmentPortArrivalDate").value,
        expected_receive_date: $("#shipmentExpectedReceiveDate").value,
        actual_signed_date: $("#shipmentActualSignedDate").value,
        actual_receive_date: $("#shipmentActualReceiveDate").value,
        note: $("#shipmentNote").value.trim(),
      }),
    });
    $("#shipmentDialog").close();
    showToast("物流信息已保存，库存时间线已重新计算");
    await loadDashboard($("#asOfInput").value);
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderReconciliation() {
  const issues = state.shipmentData?.reconciliation_issues || [];
  $("#reconciliationPanel").hidden = issues.length === 0;
  $("#reconciliationCount").textContent = `${issues.length} 条`;
  $("#reconciliationTableBody").innerHTML = issues.map((item) => `
    <tr>
      <td><strong>${escapeHtml(item.cargo_code || "待生成IBR")}</strong></td>
      <td><code>${escapeHtml(item.raw_sku)}</code></td>
      <td>${escapeHtml(item.product_name || "—")}</td>
      <td class="number">${formatQty(item.shipment_qty)}</td>
      <td>${escapeHtml(item.conflict_note || "需要人工确认")}</td>
      <td><button class="button button-secondary alias-edit-button" type="button" data-item="${escapeHtml(item.item_id)}"><i data-lucide="link"></i><span>关联MSKU</span></button></td>
    </tr>
  `).join("");
}

async function importArrivalTracking(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  form.append("store_id", $("#arrivalImportStore").value);
  form.append("as_of", $("#asOfInput").value);
  showLoading("正在导入到货跟踪", "解析IBR、SKU、开船到港日期并与领星自动对账");
  try {
    const payload = await api("/api/arrival-tracking/import", { method: "POST", body: form });
    state.shipmentData = payload.data;
    renderShipments();
    const result = payload.import;
    showToast(result.duplicate
      ? result.message
      : `${result.message}，待处理${result.unmatched_count + result.conflict_count}条`);
    if (state.dashboard) await loadDashboard($("#asOfInput").value);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    $("#arrivalImportInput").value = "";
    hideLoading();
  }
}

function openAliasDialog(itemId) {
  const issue = state.shipmentData?.reconciliation_issues.find((item) => item.item_id === itemId);
  if (!issue) return;
  state.editingAlias = issue;
  $("#aliasItemId").value = issue.item_id;
  $("#aliasStoreId").value = issue.store_id || $("#arrivalImportStore").value;
  $("#aliasDialogTitle").textContent = `${issue.raw_sku} → 领星MSKU`;
  $("#aliasMskuInput").value = "";
  const products = state.shipmentData?.match_products || [];
  $("#aliasProductOptions").innerHTML = products.map((item) =>
    `<option value="${escapeHtml(item.msku)}">${escapeHtml(item.store_name || item.store_id)} · ${escapeHtml(item.product_name || item.sku)}</option>`
  ).join("");
  $("#aliasDialog").showModal();
}

async function saveProductAlias() {
  const canonicalMsku = $("#aliasMskuInput").value.trim();
  if (!canonicalMsku) {
    showToast("请选择目标MSKU", true);
    return;
  }
  try {
    const payload = await api("/api/product-alias", {
      method: "POST",
      body: JSON.stringify({
        item_id: $("#aliasItemId").value,
        store_id: $("#aliasStoreId").value,
        canonical_msku: canonicalMsku,
        as_of: $("#asOfInput").value,
      }),
    });
    state.shipmentData = payload.data;
    $("#aliasDialog").close();
    renderShipments();
    showToast("SKU关联已保存，后续同一别名会自动匹配");
    if (state.dashboard) await loadDashboard($("#asOfInput").value);
  } catch (error) {
    showToast(error.message, true);
  }
}

function setChart(name, element, option) {
  if (!window.echarts) return;
  if (state.charts[name]) state.charts[name].dispose();
  const chart = window.echarts.init(element);
  chart.setOption(option);
  state.charts[name] = chart;
}

function renderCoverageChart() {
  const coverage = state.dashboard.summary.coverage;
  const labels = Object.keys(coverage);
  const colors = ["#c93636", "#b45309", "#0891b2", "#16845b", "#a0a8b2"];
  setChart("coverage", $("#coverageChart"), {
    animationDuration: 300,
    grid: { left: 82, right: 24, top: 18, bottom: 28 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: "{b}<br/>商品数：{c}" },
    xAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: "#edf0f3" } } },
    yAxis: { type: "category", data: labels, axisLine: { show: false }, axisTick: { show: false } },
    series: [{
      type: "bar",
      barWidth: 14,
      data: labels.map((label, index) => ({ value: coverage[label], itemStyle: { color: colors[index], borderRadius: 2 } })),
      label: { show: true, position: "right", color: "#505966" },
    }],
  });
}

function renderChannelChart() {
  const summary = state.dashboard.summary;
  const expressEnabled = settingChannelEnabled("express");
  const airEnabled = settingChannelEnabled("air");
  const channelSeries = [
    { key: "quick", name: "快船", value: summary.quick_total_qty, color: "#0284c7" },
    { key: "truck", name: "普船卡派", value: summary.truck_total_qty, color: "#0f766e" },
    { key: "slow", name: "COSCO慢船", value: summary.slow_total_qty, color: "#ca8a04" },
  ].filter((channel) => settingChannelEnabled(channel.key));
  const series = [];
  if (expressEnabled) {
    series.push({
      name: "快递",
      type: "bar",
      stack: "total",
      barWidth: 28,
      data: [summary.express_total_qty],
      label: { show: summary.express_total_qty > 0, formatter: ({ value }) => formatQty(value), color: "#fff" },
    });
  }
  if (airEnabled) {
    series.push({
      name: "空派",
      type: "bar",
      stack: "total",
      barWidth: 28,
      data: [summary.air_total_qty],
      label: { show: summary.air_total_qty > 0, formatter: ({ value }) => formatQty(value), color: "#fff" },
    });
  }
  series.push(...channelSeries.map((channel) => ({
    name: channel.name,
    type: "bar",
    stack: "total",
    barWidth: 28,
    data: [channel.value],
    label: { show: channel.value > 0, formatter: ({ value }) => formatQty(value), color: "#fff" },
  })));
  const legend = [
    ...(expressEnabled ? ["快递"] : []),
    ...(airEnabled ? ["空派"] : []),
    ...channelSeries.map((channel) => channel.name),
  ];
  const colors = [
    ...(expressEnabled ? ["#db2777"] : []),
    ...(airEnabled ? ["#7c3aed"] : []),
    ...channelSeries.map((channel) => channel.color),
  ];
  setChart("channel", $("#channelChart"), {
    animationDuration: 300,
    color: colors,
    grid: { left: 72, right: 25, top: 35, bottom: 38 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { top: 4, right: 16, data: legend },
    xAxis: { type: "value", splitLine: { lineStyle: { color: "#edf0f3" } } },
    yAxis: { type: "category", data: ["本次建议"], axisLine: { show: false }, axisTick: { show: false } },
    series,
  });
}

function filteredProducts() {
  if (!state.dashboard) return [];
  const search = $("#searchInput").value.trim().toLowerCase();
  const store = $("#storeFilter").value;
  const risk = $("#riskFilter").value;
  return state.dashboard.products.filter((item) => {
    if (store && item.store_id !== store) return false;
    if (risk && item.risk !== risk) return false;
    if (search) {
      const haystack = `${item.product_name} ${item.msku} ${item.sku} ${(item.member_mskus || []).join(" ")}`.toLowerCase();
      if (!haystack.includes(search)) return false;
    }
    if (item.is_planning_excluded && state.activeView !== "all") {
      return false;
    }
    if (state.activeView === "shipping") {
      return item.planned_ship_total > 0;
    }
    if (state.activeView === "purchase") {
      return item.next_buy_gap > 0 || item.final_buy_qty !== null && item.final_buy_qty !== undefined;
    }
    if (state.activeView === "issues") {
      return item.air_warning || item.cutoff_blocked_qty > 0 || item.overdue_inbound_qty > 0 || item.data_flags.length > 0;
    }
    return true;
  });
}

function productCell(item) {
  const image = item.image_url
    ? `<img class="product-thumb" src="${escapeHtml(item.image_url)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
    : `<span class="product-thumb"></span>`;
  return `<div class="product-cell">${image}<div><strong title="${escapeHtml(item.product_name)}">${escapeHtml(item.product_name)}</strong><small>${escapeHtml(productMskuSummary(item))}</small>${item.is_planning_excluded ? planningStatusBadge(item) : ""}</div></div>`;
}

function shippingProductCell(item) {
  const image = item.image_url
    ? `<img class="product-thumb" src="${escapeHtml(item.image_url)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
    : `<span class="product-thumb"></span>`;
  return `<div class="product-cell shipping-product-cell">${image}<div><strong title="${escapeHtml(item.product_name)}">${escapeHtml(item.product_name)}</strong>${item.is_planning_excluded ? planningStatusBadge(item) : ""}</div></div>`;
}

function coverageCell(item) {
  if (item.sellable_coverage_days === null) return `<span class="muted">无销量</span>`;
  const percent = Math.min(100, item.sellable_coverage_days / Math.max(1, item.quick_target_coverage_days) * 100);
  const className = item.sellable_coverage_days < item.normal_target_coverage_days ? "is-low" : item.sellable_coverage_days < item.normal_target_coverage_days + 25 ? "is-mid" : "";
  return `<div><strong>${formatDecimal(item.sellable_coverage_days)}天</strong><div class="coverage-bar ${className}"><span style="width:${percent}%"></span></div></div>`;
}

function recommendedRouteSummary(item) {
  const routes = item.channel_plans
    .filter((plan) => plan.enabled)
    .map((plan) => {
      const confirmed = item[`confirmed_${plan.key}_qty`];
      const quantity = confirmed === null || confirmed === undefined
        ? Number(item[`${plan.key}_qty`] || 0)
        : Number(confirmed || 0);
      return { ...plan, quantity };
    })
    .filter((plan) => plan.quantity > 0);
  if (!routes.length) {
    return { channels: "无需发货", arrivals: "—" };
  }
  return {
    channels: routes.map((route) => `${route.label} ${formatQty(route.quantity)}件`).join("；"),
    arrivals: routes.map((route) => `${route.label} ${formatDate(route.planning_arrival_date || route.arrival_date)}`).join("；"),
  };
}

function activeShippingChannels(item) {
  return (item.channel_plans || [])
    .filter((plan) => plan.enabled)
    .sort((left, right) => String(left.planning_arrival_date || left.arrival_date).localeCompare(String(right.planning_arrival_date || right.arrival_date)));
}

function channelCoverageDays(item, plan, channels) {
  const regularChannels = channels.filter((channel) => !["express", "air"].includes(channel.key));
  const seasonalChannel = regularChannels.reduce((latest, channel) => (
    !latest || String(channel.planning_arrival_date || channel.arrival_date) > String(latest.planning_arrival_date || latest.arrival_date)
      ? channel
      : latest
  ), null);
  return seasonalChannel?.key === plan.key
    ? item.current_total_coverage_days
    : plan.target_coverage_days;
}

function shippingRow(item) {
  const channels = activeShippingChannels(item);
  const coverageCells = channels
    .map((plan) => `<td class="number">${formatDecimal(channelCoverageDays(item, plan, channels), 4)}</td>`)
    .join("");
  const quantityCells = channels
    .map((plan) => `<td class="number quantity-strong">${formatQty(item[`${plan.key}_qty`] || 0)}</td>`)
    .join("");
  return `
    <td>${shippingProductCell(item)}</td>
    <td><strong>${escapeHtml(item.execution_msku || item.msku)}</strong>${item.is_grouped ? `<small class="block-muted">合并：${escapeHtml(productMemberMskus(item).join(" / "))}</small>` : ""}</td>
    <td class="number">${formatDecimal(item.avg_7, 2)}</td>
    <td class="number">${formatDecimal(item.avg_14, 2)}</td>
    <td class="number">${formatDecimal(item.avg_30, 2)}</td>
    <td class="number">${formatDecimal(item.dynamic_daily, 2)}</td>
    <td class="number">${formatQty(item.fbt_total)}</td>
    <td class="number">${formatQty(item.fbt_sellable)}</td>
    <td class="number">${formatQty(item.fbt_in_transit)}</td>
    <td class="number">${formatDecimal(item.safety_buffer_days, 2)}</td>
    <td class="number">${formatDecimal(item.dispatch_interval_days, 2)}</td>
    ${coverageCells}
    ${quantityCells}`;
}

function purchaseRow(item) {
  const finalValue = item.final_buy_qty === null || item.final_buy_qty === undefined ? "待确认" : formatQty(item.final_buy_qty);
  return `
    <td>${riskBadge(item)}</td>
    <td>${productCell(item)}</td>
    <td class="number">${formatDecimal(item.dynamic_daily, 2)}</td>
    <td class="number">${formatDecimal(item.next_total_coverage_days, 4)}</td>
    <td class="number">${formatQty(item.next_target_units)}</td>
    <td class="number">${formatQty(item.inventory_position)}</td>
    <td class="number">${formatQty(item.planned_ship_total)}</td>
    <td class="number quantity-strong">${formatQty(item.next_buy_gap)}</td>
    <td class="number">${finalValue}</td>
    <td><span class="source-badge status-badge">待人工核对</span></td>
    <td>${statusBadge(item)}</td>`;
}

function issueRow(item) {
  const flags = [
    ...(item.urgent_warning ? [item.urgent_too_late ? "即使最快加急渠道也存在断货窗口" : "最快常规渠道入仓前存在断货窗口"] : []),
    ...(item.overdue_inbound_qty > 0 ? [`${formatQty(item.overdue_inbound_qty)}件IBR已逾期未接收`] : []),
    ...(item.cutoff_blocked_qty > 0 ? [`${formatQty(item.cutoff_blocked_qty)}件受停止收货日阻断`] : []),
    ...item.data_flags,
  ];
  return `
    <td>${riskBadge(item)}</td>
    <td>${productCell(item)}</td>
    <td>${coverageCell(item)}</td>
    <td>${formatDate(item.stockout_date)}</td>
    <td>${escapeHtml(item.regular_fastest_channel_label)} · ${formatDate(item.channel_plans.find((plan) => plan.key === item.regular_fastest_channel)?.planning_arrival_date)}</td>
    <td><div class="issue-list">${flags.map((flag) => `<span class="issue-chip">${escapeHtml(flag)}</span>`).join("")}</div></td>
    <td>${statusBadge(item)}</td>`;
}

function renderTable() {
  if (!state.dashboard) return;
  const sampleItem = state.dashboard.products[0];
  const activeChannels = sampleItem ? activeShippingChannels(sampleItem) : [];
  const shippingHeads = [
    "品名",
    "MSKU",
    "7天销量",
    "14天销量",
    "30天销量",
    "预测日销量",
    "FBT库存",
    "FBT可售",
    "FBT在途",
    "安全天数",
    "本地仓发货频率",
    ...activeChannels.map((channel) => channel.label),
    ...activeChannels.map((channel) => `${channel.label}建议补货`),
  ];
  const heads = {
    shipping: shippingHeads,
    purchase: ["风险", "商品 / MSKU", "动态日均", "下次旺季目标覆盖", "下次目标件数", "库存位置", "本次计划发货", "理论买货缺口", "最终买货量", "数据口径", "状态"],
    issues: ["风险", "商品 / MSKU", "当前可售覆盖", "预计断货", "最快常规渠道入仓", "原因", "状态"],
    all: shippingHeads,
  }[state.activeView];
  $("#tableHead").innerHTML = `<tr>${heads.map((head) => `<th>${head}</th>`).join("")}</tr>`;

  const products = filteredProducts();
  $("#tableCount").textContent = `${products.length} 个商品`;
  const renderer = state.activeView === "purchase" ? purchaseRow : state.activeView === "issues" ? issueRow : shippingRow;
  $("#tableBody").innerHTML = products.length
    ? products.map((item) => `<tr data-key="${escapeHtml(item.store_id)}|${escapeHtml(item.msku)}">${renderer(item)}</tr>`).join("")
    : `<tr><td class="empty-row" colspan="${heads.length}">当前筛选条件下没有商品</td></tr>`;
}

function renderSchedule() {
  if (!state.schedule.length) return;
  const context = state.dashboard?.schedule_context;
  const currentDate = context?.current.week_date;
  const nextDate = context?.next.week_date;
  const representativeProduct = state.dashboard?.products?.[0];
  const safetyDays = Number(representativeProduct?.safety_buffer_days || 0);
  const intervalDays = Number(representativeProduct?.dispatch_interval_days || 0);
  const seasonalChannelLabel = representativeProduct?.seasonal_channel_label || "旺季渠道";
  const totalCoverage = (item) => (
    Number(item.seasonal_coverage_days) + safetyDays + intervalDays
  );
  $("#scheduleTableBody").innerHTML = state.schedule.map((item, index) => {
    const previous = index ? Number(state.schedule[index - 1].seasonal_coverage_days) : 0;
    const delta = Number(item.seasonal_coverage_days) - previous;
    const rowClass = item.week_date === currentDate ? "row-current" : item.week_date === nextDate ? "row-next" : "";
    const status = item.week_date === currentDate ? "本次发货" : item.week_date === nextDate ? "下次买货" : item.week_date < currentDate ? "已过" : "计划中";
    return `<tr class="${rowClass}">
      <td>${index + 1}</td>
      <td><input class="schedule-date-input" type="date" value="${escapeHtml(item.week_date)}" data-index="${index}"></td>
      <td><input class="schedule-days-input" type="number" min="0" step="0.0001" value="${item.seasonal_coverage_days}" data-index="${index}"></td>
      <td>${formatDecimal(safetyDays)} 天<small class="block-muted">${escapeHtml(seasonalChannelLabel)}</small></td>
      <td>${formatDecimal(intervalDays)} 天<small class="block-muted">${escapeHtml(seasonalChannelLabel)}</small></td>
      <td><strong>${formatDecimal(totalCoverage(item), 4)} 天</strong></td>
      <td>+${formatDecimal(delta, 4)} 天</td>
      <td><span class="status-badge">${status}</span></td>
    </tr>`;
  }).join("");

  setChart("schedule", $("#scheduleChart"), {
    animationDuration: 300,
    color: ["#2563eb"],
    grid: { left: 55, right: 28, top: 34, bottom: 62 },
    legend: { data: ["最终目标覆盖"], top: 2 },
    tooltip: {
      trigger: "axis",
      formatter: (items) => `${formatDate(items[0].axisValue)}<br/>${items.map((item) => `${item.marker}${item.seriesName}：${formatDecimal(item.value, 4)}天`).join("<br/>")}`,
    },
    xAxis: { type: "category", data: state.schedule.map((item) => item.week_date), axisLabel: { rotate: 35, formatter: formatDate }, boundaryGap: false },
    yAxis: { type: "value", name: "覆盖天数", splitLine: { lineStyle: { color: "#edf0f3" } } },
    series: [
      {
        name: "最终目标覆盖",
        type: "line",
        step: "end",
        symbolSize: 7,
        data: state.schedule.map(totalCoverage),
        lineStyle: { width: 3 },
        areaStyle: { color: "rgba(37,99,235,.08)" },
        markPoint: currentDate ? { data: [{ name: "本次", coord: [currentDate, totalCoverage(context.current)], value: "本次" }], itemStyle: { color: "#2563eb" } } : undefined,
      },
    ],
  });
}

function populateSettings() {
  if (!state.settings) return;
  const settings = state.settings;
  CHANNEL_UI.forEach((channel) => {
    $(`#${channel.key}ChannelEnabledInput`).checked = settings[channel.setting] !== false;
    $(`#${channel.key}SafetyInput`).value = settings[`${channel.key}_safety_days`];
    $(`#${channel.key}FrequencyInput`).value = settings[`${channel.key}_frequency_days`];
  });
  $("#timingModeInput").value = settings.timing_mode || "precise";
  $("#expressMinInput").value = settings.express_transit_min_days;
  $("#expressMaxInput").value = settings.express_transit_max_days;
  $("#airMinInput").value = settings.air_transit_min_days;
  $("#airMaxInput").value = settings.air_transit_max_days;
  $("#quickMinInput").value = settings.quick_transit_min_days;
  $("#quickMaxInput").value = settings.quick_transit_max_days;
  $("#truckMinInput").value = settings.truck_transit_min_days;
  $("#truckMaxInput").value = settings.truck_transit_max_days;
  $("#slowMinInput").value = settings.slow_transit_min_days;
  $("#slowMaxInput").value = settings.slow_transit_max_days;
  populateWeekdaySelect("#quickCutoffInput", settings.quick_cutoff_weekday);
  populateWeekdaySelect("#quickSailingInput", settings.quick_sailing_weekday);
  populateWeekdaySelect("#truckCutoffInput", settings.truck_cutoff_weekday);
  populateWeekdaySelect("#truckSailingInput", settings.truck_sailing_weekday);
  populateWeekdaySelect("#slowCutoffInput", settings.slow_cutoff_weekday);
  populateWeekdaySelect("#slowSailingInput", settings.slow_sailing_weekday);
  $("#cutoffInput").value = settings.receiving_cutoff;
  $("#weight7Input").value = Math.round(settings.weight_7 * 100);
  $("#weight14Input").value = Math.round(settings.weight_14 * 100);
  $("#weight30Input").value = Math.round(settings.weight_30 * 100);
  updateSettingsPreview();
}

function updateChannelSettingCards() {
  CHANNEL_UI.forEach((channel) => {
    const input = $(`#${channel.key}ChannelEnabledInput`);
    input.closest(".channel-setting-card")?.classList.toggle("is-disabled", !input.checked);
  });
}

function populateWeekdaySelect(selector, selectedValue) {
  const names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  const select = $(selector);
  select.innerHTML = names.map((name, index) => `<option value="${index}">${name}</option>`).join("");
  select.value = String(selectedValue);
}

function updateSettingsPreview() {
  updateChannelSettingCards();
  const expressEnabled = $("#expressChannelEnabledInput").checked;
  const airEnabled = $("#airChannelEnabledInput").checked;
  const timingMode = $("#timingModeInput").value;
  const enabledChannels = CHANNEL_UI
    .filter((channel) => $(`#${channel.key}ChannelEnabledInput`).checked)
    .map((channel) => ({
      ...channel,
      safety: Number($(`#${channel.key}SafetyInput`).value || 0),
      frequency: Number($(`#${channel.key}FrequencyInput`).value || 0),
    }));
  $("#timingModePreview").textContent = timingMode === "precise"
    ? "精准船期：最近截单 → 开船 → 最慢运输时效 → 安全缓冲；海运不再重复加发货频率"
    : "安全 + 频率：最慢运输时效 + 安全缓冲 + 发货频率";
  $("#airFormulaPreview").textContent = `；快递${expressEnabled ? "开启" : "关闭"}，空派${airEnabled ? "开启" : "关闭"}`;
  $("#channelCoveragePreview").textContent = `；最终到货日：${enabledChannels
    .map((channel) => {
      const frequency = ["express", "air"].includes(channel.key) || timingMode === "fixed"
        ? `+频率${channel.frequency}`
        : "+精确船期等待";
      return `${channel.label} 最慢时效+安全${channel.safety}${frequency}`;
    })
    .join("；")}`;
  const total = ["#weight7Input", "#weight14Input", "#weight30Input"].reduce((sum, selector) => sum + Number($(selector).value || 0), 0);
  $("#weightTotalPreview").textContent = `${total}%`;
  $("#weightTotalPreview").style.color = total === 100 ? "#16845b" : "#c93636";
}

async function saveSettings() {
  const weights = [Number($("#weight7Input").value), Number($("#weight14Input").value), Number($("#weight30Input").value)];
  if (weights.some((value) => !Number.isFinite(value) || value < 0) || Math.abs(weights.reduce((a, b) => a + b, 0) - 100) > 0.001) {
    showToast("近7日/14日/30日平均销量权重必须合计为100%", true);
    return;
  }
  const regularChannelEnabled = ["quick", "truck", "slow"]
    .some((key) => $(`#${key}ChannelEnabledInput`).checked);
  if (!regularChannelEnabled) {
    showToast("至少需要保留一个常规物流渠道参与建议", true);
    return;
  }
  const expressEnabled = $("#expressChannelEnabledInput").checked;
  const airEnabled = $("#airChannelEnabledInput").checked;
  const rangePairs = [
    ["快递", "#expressMinInput", "#expressMaxInput"],
    ["空派", "#airMinInput", "#airMaxInput"],
    ["快船", "#quickMinInput", "#quickMaxInput"],
    ["普船卡派", "#truckMinInput", "#truckMaxInput"],
    ["COSCO慢船", "#slowMinInput", "#slowMaxInput"],
  ];
  for (const [label, minSelector, maxSelector] of rangePairs) {
    const minValue = Number($(minSelector).value);
    const maxValue = Number($(maxSelector).value);
    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue) || minValue <= 0 || maxValue < minValue) {
      showToast(`${label}时效范围无效：最慢天数必须大于等于最快天数`, true);
      return;
    }
  }
  for (const channel of CHANNEL_UI) {
    const safety = Number($(`#${channel.key}SafetyInput`).value);
    const frequency = Number($(`#${channel.key}FrequencyInput`).value);
    if (!Number.isFinite(safety) || safety < 0 || !Number.isFinite(frequency) || frequency < 0) {
      showToast(`${channel.label}的安全缓冲和发货频率不能小于0`, true);
      return;
    }
  }
  if (!$("#cutoffInput").value) {
    showToast("请设置停止接收入仓日期", true);
    return;
  }
  const settings = {
    air_enabled: airEnabled,
    express_channel_enabled: expressEnabled,
    air_channel_enabled: $("#airChannelEnabledInput").checked,
    quick_channel_enabled: $("#quickChannelEnabledInput").checked,
    truck_channel_enabled: $("#truckChannelEnabledInput").checked,
    slow_channel_enabled: $("#slowChannelEnabledInput").checked,
    timing_mode: $("#timingModeInput").value,
    express_transit_min_days: Number($("#expressMinInput").value),
    express_transit_max_days: Number($("#expressMaxInput").value),
    air_transit_min_days: Number($("#airMinInput").value),
    air_transit_max_days: Number($("#airMaxInput").value),
    quick_transit_min_days: Number($("#quickMinInput").value),
    quick_transit_max_days: Number($("#quickMaxInput").value),
    quick_cutoff_weekday: Number($("#quickCutoffInput").value),
    quick_sailing_weekday: Number($("#quickSailingInput").value),
    truck_transit_min_days: Number($("#truckMinInput").value),
    truck_transit_max_days: Number($("#truckMaxInput").value),
    truck_cutoff_weekday: Number($("#truckCutoffInput").value),
    truck_sailing_weekday: Number($("#truckSailingInput").value),
    slow_transit_min_days: Number($("#slowMinInput").value),
    slow_transit_max_days: Number($("#slowMaxInput").value),
    slow_cutoff_weekday: Number($("#slowCutoffInput").value),
    slow_sailing_weekday: Number($("#slowSailingInput").value),
    express_safety_days: Number($("#expressSafetyInput").value),
    express_frequency_days: Number($("#expressFrequencyInput").value),
    air_safety_days: Number($("#airSafetyInput").value),
    air_frequency_days: Number($("#airFrequencyInput").value),
    quick_safety_days: Number($("#quickSafetyInput").value),
    quick_frequency_days: Number($("#quickFrequencyInput").value),
    truck_safety_days: Number($("#truckSafetyInput").value),
    truck_frequency_days: Number($("#truckFrequencyInput").value),
    slow_safety_days: Number($("#slowSafetyInput").value),
    slow_frequency_days: Number($("#slowFrequencyInput").value),
    receiving_cutoff: $("#cutoffInput").value,
    weight_7: weights[0] / 100,
    weight_14: weights[1] / 100,
    weight_30: weights[2] / 100,
  };
  try {
    await api("/api/settings", { method: "POST", body: JSON.stringify({ settings }) });
    showToast("参数已保存并重新计算");
    await loadDashboard($("#asOfInput").value);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveSchedule() {
  const dates = $$(".schedule-date-input");
  const days = $$(".schedule-days-input");
  const schedule = dates.map((input, index) => ({ week_date: input.value, seasonal_coverage_days: Number(days[index].value) }));
  if (schedule.some((item) => !item.week_date || !Number.isFinite(item.seasonal_coverage_days) || item.seasonal_coverage_days < 0)) {
    showToast("请检查统计周和旺季发货覆盖天数", true);
    return;
  }
  try {
    const payload = await api("/api/schedule", { method: "POST", body: JSON.stringify({ schedule }) });
    state.schedule = payload.schedule;
    showToast("旺季计划已保存");
    if (state.dashboard) await loadDashboard($("#asOfInput").value);
    else renderSchedule();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function pullLatest() {
  showLoading("正在拉取领星数据", "查询TikTok商品、销量、FBT库存、IBR货件和发货单");
  try {
    const payload = await api("/api/pull-latest", { method: "POST", body: JSON.stringify({}) });
    state.dashboard = payload.data;
    state.settings = payload.data.settings;
    state.schedule = payload.data.schedule;
    $("#emptyState").hidden = true;
    $("#dashboardContent").hidden = false;
    $("#asOfInput").value = payload.data.as_of;
    sourceStamp(payload.data.snapshot);
    renderDashboard();
    await loadShipments(payload.data.as_of);
    state.purchasePlan = null;
    if (state.activePage === "purchase") await loadPurchasePlan(payload.data.as_of);
    populateSettings();
    renderSchedule();
    showToast("领星数据已更新");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    hideLoading();
  }
}

async function openDetail(storeId, msku) {
  showLoading("正在计算单品", "生成库存预测和建议说明");
  try {
    const params = new URLSearchParams({ store_id: storeId, msku, as_of: $("#asOfInput").value });
    const payload = await api(`/api/product?${params}`);
    state.currentDetail = payload.data;
    state.manualScenarioNodes = initialScenarioNodes(payload.data.product);
    state.manualScenarioResult = null;
    state.scenarioDirty = false;
    renderDetail(payload.data);
    $("#drawerBackdrop").hidden = false;
    $("#detailDrawer").classList.add("is-open");
    $("#detailDrawer").setAttribute("aria-hidden", "false");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    hideLoading();
  }
}

function metricBox(label, value, source = "系统") {
  return `<div class="detail-metric"><span>${label} · ${source}</span><strong>${value}</strong></div>`;
}

function scenarioNodeId() {
  return `scenario-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function channelInfo(key) {
  return CHANNEL_UI.find((channel) => channel.key === key)
    || { key, label: key };
}

function initialScenarioNodes(item, useSaved = true) {
  const saved = useSaved ? (item.confirmed_scenario_nodes || []) : [];
  if (saved.length) {
    return saved.map((node, index) => ({
      ...node,
      id: node.id || `saved-${index + 1}`,
      channel_key: node.channel_key || node.key,
      label: node.label || channelInfo(node.channel_key || node.key).label,
      dispatch_date: node.dispatch_date || node.planned_dispatch_date,
      arrival_date: node.planning_arrival_date || node.arrival_date,
      planning_arrival_date: node.planning_arrival_date || node.arrival_date,
      quantity: Math.max(0, Number(node.quantity || 0)),
      quantity_locked: Boolean(node.quantity_locked),
      auto_generated: Boolean(node.auto_generated),
    }));
  }
  return (item.channel_plans || [])
    .filter((plan) => plan.enabled && Number(
      item[`confirmed_${plan.key}_qty`] ?? item[`${plan.key}_qty`] ?? 0,
    ) > 0)
    .map((plan, index) => ({
      ...plan,
      id: `system-${plan.key}-${index + 1}`,
      channel_key: plan.key,
      dispatch_date: item.planned_dispatch_date,
      arrival_date: plan.planning_arrival_date || plan.arrival_date,
      planning_arrival_date: plan.planning_arrival_date || plan.arrival_date,
      manual_arrival_override: false,
      quantity_locked: false,
      auto_generated: false,
      quantity: Math.max(0, Number(
        item[`confirmed_${plan.key}_qty`] ?? item[`${plan.key}_qty`] ?? 0,
      )),
    }));
}

function scenarioChannelOptions(item, selectedKey) {
  return CHANNEL_UI
    .filter((channel) => itemChannelEnabled(item, channel.key))
    .map((channel) => `
      <option value="${channel.key}" ${channel.key === selectedKey ? "selected" : ""}>
        ${escapeHtml(channel.label)}
      </option>`)
    .join("");
}

function updateScenarioSummary() {
  const result = state.manualScenarioResult;
  const total = state.manualScenarioNodes.reduce(
    (sum, node) => sum + Number(node.quantity || 0),
    0,
  );
  const element = $("#scenarioSummary");
  if (!element) return;
  if (!result) {
    element.textContent = `${state.manualScenarioNodes.length}个节点，共${formatQty(total)}件`;
    return;
  }
  element.textContent = [
    `自动重算${formatQty(result.planned_ship_total)}件`,
    `人工固定${formatQty(result.locked_ship_total || 0)}件`,
    `其余自动调整${formatQty(result.auto_adjusted_total || 0)}件`,
    result.stockout_protected
      ? "预计不断货"
      : `${result.first_uncovered_date || "近期"}仍缺${formatQty(result.uncovered_shortage_qty || 0)}件`,
    result.cutoff_blocked_qty > 0
      ? `阻断${formatQty(result.cutoff_blocked_qty)}件`
      : "停止收货日前可安排",
  ].join(" · ");
}

function renderScenarioPlanner() {
  const container = $("#scenarioNodeList");
  const item = state.currentDetail?.product;
  if (!container || !item) return;
  if (!state.manualScenarioNodes.length) {
    container.innerHTML = `
      <div class="scenario-empty">
        尚未安排发货节点。新增节点后，系统会重新计算总量和渠道接力。
      </div>`;
  } else {
    container.innerHTML = state.manualScenarioNodes.map((node) => {
      const eligible = node.eligible_before_cutoff !== false;
      return `
        <div class="scenario-node ${eligible ? "" : "is-blocked"}" data-scenario-node="${escapeHtml(node.id)}">
          <label class="control">
            <span>计划发货日</span>
            <input type="date" data-scenario-field="dispatch_date" value="${escapeHtml(node.dispatch_date || "")}">
          </label>
          <label class="control">
            <span>物流渠道</span>
            <select data-scenario-field="channel_key">
              ${scenarioChannelOptions(item, node.channel_key)}
            </select>
          </label>
          <label class="control">
            <span>预计FBT入仓日</span>
            <input type="date" data-scenario-field="arrival_date" value="${escapeHtml(node.planning_arrival_date || node.arrival_date || "")}">
          </label>
          <label class="control">
            <span>本节点数量</span>
            <input type="number" min="0" data-scenario-field="quantity" value="${Math.max(0, Number(node.quantity || 0))}">
          </label>
          <div class="scenario-node-meta">
            <span>${node.auto_generated ? "系统自动接力" : (node.manual_arrival_override ? "人工入仓日" : "按渠道参数计算")}</span>
            <label class="scenario-quantity-lock">
              <input type="checkbox" data-scenario-lock ${node.quantity_locked ? "checked" : ""}>
              <span>${node.quantity_locked ? "人工固定量" : "交给系统调整"}</span>
            </label>
            ${eligible ? "" : "<strong>晚于停止收货日</strong>"}
          </div>
          <button class="icon-button scenario-remove" type="button" data-scenario-remove="${escapeHtml(node.id)}" title="删除发货节点">
            <i data-lucide="trash-2"></i>
          </button>
        </div>`;
    }).join("");
  }

  $$("[data-scenario-field]").forEach((input) => {
    const eventName = input.dataset.scenarioField === "quantity"
      ? "input"
      : "change";
    input.addEventListener(eventName, () => {
      const row = input.closest("[data-scenario-node]");
      const node = state.manualScenarioNodes.find(
        (candidate) => candidate.id === row?.dataset.scenarioNode,
      );
      if (!node) return;
      const field = input.dataset.scenarioField;
      if (field === "quantity") {
        node.quantity = Math.max(0, Number(input.value || 0));
        node.quantity_locked = true;
        const lockInput = row.querySelector("[data-scenario-lock]");
        if (lockInput) lockInput.checked = true;
        state.manualScenarioResult = null;
        state.scenarioDirty = true;
        updateScenarioSummary();
        renderForecastChart(state.currentDetail);
        scheduleScenarioRecalculation();
        return;
      }
      state.scenarioDirty = true;
      node[field] = input.value;
      if (field === "arrival_date") {
        node.planning_arrival_date = input.value;
        node.manual_arrival_override = true;
      } else {
        node.arrival_date = "";
        node.planning_arrival_date = "";
        node.manual_arrival_override = false;
      }
      scheduleScenarioRecalculation();
    });
  });
  $$('[data-scenario-lock]').forEach((input) => {
    input.addEventListener("change", () => {
      const row = input.closest("[data-scenario-node]");
      const node = state.manualScenarioNodes.find(
        (candidate) => candidate.id === row?.dataset.scenarioNode,
      );
      if (!node) return;
      node.quantity_locked = input.checked;
      state.scenarioDirty = true;
      scheduleScenarioRecalculation();
    });
  });
  $$("[data-scenario-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      state.manualScenarioNodes = state.manualScenarioNodes.filter(
        (node) => node.id !== button.dataset.scenarioRemove,
      );
      recalculateScenario();
    });
  });
  updateScenarioSummary();
  icons();
}

function scheduleScenarioRecalculation() {
  clearTimeout(state.scenarioRecalcTimer);
  state.scenarioRecalcTimer = setTimeout(recalculateScenario, 260);
}

async function recalculateScenario() {
  const detail = state.currentDetail;
  if (!detail) return;
  const item = detail.product;
  try {
    const payload = await api("/api/scenario", {
      method: "POST",
      body: JSON.stringify({
        store_id: item.store_id,
        msku: item.canonical_msku || item.msku,
        as_of: detail.as_of,
        executed_unsynced_qty: Number($("#decisionUnsynced")?.value || 0),
        nodes: state.manualScenarioNodes.map((node) => ({
          id: node.id,
          channel_key: node.channel_key,
          dispatch_date: node.dispatch_date,
          arrival_date: node.manual_arrival_override
            ? (node.planning_arrival_date || node.arrival_date)
            : "",
          quantity: Math.max(0, Number(node.quantity || 0)),
          quantity_locked: Boolean(node.quantity_locked),
          auto_generated: Boolean(node.auto_generated),
        })),
      }),
    });
    state.manualScenarioResult = payload.data.scenario;
    state.manualScenarioNodes = payload.data.scenario.nodes;
    state.scenarioDirty = true;
    if ($("#decisionBuy")) {
      $("#decisionBuy").value = payload.data.scenario.next_buy_gap;
    }
    renderScenarioPlanner();
    renderForecastChart(detail);
  } catch (error) {
    showToast(error.message, true);
  }
}

function addScenarioNode() {
  const item = state.currentDetail?.product;
  if (!item) return;
  const firstEnabled = CHANNEL_UI.find(
    (channel) => itemChannelEnabled(item, channel.key),
  );
  if (!firstEnabled) {
    showToast("没有可用物流渠道", true);
    return;
  }
  state.manualScenarioNodes.push({
    id: scenarioNodeId(),
    channel_key: firstEnabled.key,
    label: firstEnabled.label,
    dispatch_date: item.planned_dispatch_date,
    arrival_date: "",
    planning_arrival_date: "",
    manual_arrival_override: false,
    quantity_locked: false,
    auto_generated: false,
    quantity: 0,
  });
  recalculateScenario();
}

function resetScenarioNodes() {
  const item = state.currentDetail?.product;
  if (!item) return;
  state.manualScenarioNodes = initialScenarioNodes(item, false);
  state.manualScenarioResult = null;
  state.scenarioDirty = false;
  if ($("#decisionBuy")) $("#decisionBuy").value = item.next_buy_gap;
  renderScenarioPlanner();
  renderForecastChart(state.currentDetail);
}

function renderChannelTimeline(detail) {
  const item = detail.product;
  const channels = activeShippingChannels(item)
    .map((channel) => ({
      ...channel,
      days: Number(channel.arrival_days || 0),
      arrival: channel.arrival_date,
      quantity: channel.recommended_qty,
    }));
  const maxDays = Math.max(1, ...channels.map((channel) => channel.days));
  const seasonalChannel = channels
    .filter((channel) => !["express", "air"].includes(channel.key))
    .reduce((latest, channel) => (
      !latest || String(channel.arrival) > String(latest.arrival)
        ? channel
        : latest
    ), null);
  const targetDescription = (channel) => {
    if (seasonalChannel?.key === channel.key) {
      const coverageDate = addDays(detail.as_of, item.current_total_coverage_days);
      return `旺季目标覆盖到${formatDate(coverageDate)} · ${formatDecimal(item.current_total_coverage_days, 4)}天 = 旺季基础${formatDecimal(item.current_seasonal_coverage_days, 4)}天 + 安全${formatDecimal(channel.safety_days)}天 + 本模式采用频率${formatDecimal(channel.applied_frequency_days)}天`;
    }
    if (channel.schedule_applied && !["express", "air"].includes(channel.key)) {
      return `${formatDate(channel.cutoff_date)}截单 / ${formatDate(channel.sailing_date)}开船 + 最慢运输${formatDecimal(channel.transit_max_days)}天 + 安全${formatDecimal(channel.safety_days)}天`;
    }
    return `最慢运输${formatDecimal(channel.transit_max_days)}天 + 安全${formatDecimal(channel.safety_days)}天 + 频率${formatDecimal(channel.applied_frequency_days)}天`;
  };
  return `
    <div class="channel-timeline" aria-label="物流渠道预计入仓时间">
      ${channels.map((channel) => `
        <div class="channel-lane is-${channel.key}">
          <span class="channel-lane-label"><i></i>${channel.label}</span>
          <span class="channel-lane-track"><b style="--timeline-width:${Math.max(3, channel.days / maxDays * 100)}%"></b></span>
          <span class="channel-lane-meta">${formatDate(item.planned_dispatch_date)}计划发货 → ${formatDate(channel.arrival)}最终预计到货 · ${targetDescription(channel)} · <span data-channel-preview-quantity="${channel.key}">${formatQty(channel.quantity)}件</span></span>
        </div>`).join("")}
    </div>`;
}

function renderDetail(detail) {
  const item = detail.product;
  $("#drawerImage").src = item.image_url || "";
  $("#drawerImage").style.visibility = item.image_url ? "visible" : "hidden";
  $("#drawerName").textContent = item.product_name;
  $("#drawerMsku").textContent = productMskuSummary(item);
  $("#drawerStore").textContent = item.store_name;
  $("#drawerRisk").innerHTML = riskBadge(item);

  const finalBuy = item.final_buy_qty ?? item.next_buy_gap;
  const confirmedExpress = item.confirmed_express_qty ?? item.express_qty;
  const confirmedAir = item.confirmed_air_qty ?? item.air_qty;
  const confirmedQuick = item.confirmed_quick_qty ?? item.quick_qty;
  const confirmedTruck = item.confirmed_truck_qty ?? item.truck_qty;
  const confirmedSlow = item.confirmed_slow_qty ?? item.slow_qty;
  const enabledUrgentChannels = CHANNEL_UI
    .filter((channel) => ["express", "air"].includes(channel.key) && itemChannelEnabled(item, channel.key));
  const enabledRegularChannels = CHANNEL_UI
    .filter((channel) => !["express", "air"].includes(channel.key) && itemChannelEnabled(item, channel.key));
  const channelQuantities = {
    express: { suggested: item.express_qty, confirmed: confirmedExpress, input: "decisionExpress" },
    air: { suggested: item.air_qty, confirmed: confirmedAir, input: "decisionAir" },
    quick: { suggested: item.quick_qty, confirmed: confirmedQuick, input: "decisionQuick" },
    truck: { suggested: item.truck_qty, confirmed: confirmedTruck, input: "decisionTruck" },
    slow: { suggested: item.slow_qty, confirmed: confirmedSlow, input: "decisionSlow" },
  };
  const urgentRecommendations = enabledUrgentChannels.map((channel) => `
    <div class="recommendation-item"><span>本次${channel.label}</span><strong>${formatQty(channelQuantities[channel.key].suggested)}</strong></div>
  `).join("");
  const urgentDecisions = enabledUrgentChannels.map((channel) => `
    <label class="control"><span>最终${channel.label}量</span><input id="${channelQuantities[channel.key].input}" type="number" min="0" value="${channelQuantities[channel.key].confirmed}"></label>
  `).join("");
  const regularRecommendations = enabledRegularChannels.map((channel) => `
    <div class="recommendation-item"><span>本次${channel.label}</span><strong>${formatQty(channelQuantities[channel.key].suggested)}</strong></div>
  `).join("");
  const regularDecisions = enabledRegularChannels.map((channel) => `
    <label class="control"><span>最终${channel.label}量</span><input id="${channelQuantities[channel.key].input}" type="number" min="0" value="${channelQuantities[channel.key].confirmed}"></label>
  `).join("");
  const channelResultParts = [
    ...[...enabledUrgentChannels, ...enabledRegularChannels]
      .filter((channel) => Number(channelQuantities[channel.key].suggested || 0) > 0)
      .map((channel) => `${channel.label} ${formatQty(channelQuantities[channel.key].suggested)}`),
  ];
  const channelResultText = channelResultParts.length
    ? channelResultParts.join(" + ")
    : "无需发货";
  const fbtAll = item.fbt_all ?? (item.fbt_total + item.fbt_in_transit);
  const [planningStatusLabel] = planningStatusInfo(item.planning_status);
  const planningStatusHint = item.is_planning_excluded
    ? `该商品已标记为${planningStatusLabel}，保留销量、库存和IBR记录，但不生成发货、买货和备货建议。`
    : "正常参与每周发货、下次买货和旺季备货计算。";
  const planningInbounds = item.planning_inbounds
    || item.inbounds?.filter((inbound) => inbound.eta_date && !inbound.is_overdue && !inbound.is_after_cutoff)
    || [];
  const activeInbounds = [...(item.inbounds || [])].sort((left, right) => {
    const leftDate = left.eta_date || "9999-12-31";
    const rightDate = right.eta_date || "9999-12-31";
    return leftDate.localeCompare(rightDate)
      || String(left.cargo_code || "").localeCompare(String(right.cargo_code || ""));
  });
  const plannedShipTotal = item.planned_ship_total
    ?? (Number(item.express_qty || 0) + Number(item.air_qty || 0) + Number(item.quick_qty || 0) + Number(item.truck_qty || 0) + Number(item.slow_qty || 0));
  const fastestRegularPlan = item.channel_plans.find((plan) => plan.key === item.regular_fastest_channel);
  const timingRiskText = Number(item.dynamic_daily || 0) <= 0
    ? "暂无有效销量"
    : item.urgent_warning
      ? `会，预计${formatDate(item.stockout_date)}`
      : "暂不会";
  const inboundStatus = (inbound) => {
    if (!inbound.eta_date) {
      return '<span class="issue-chip">待补入库日</span>';
    }
    if (inbound.is_overdue) {
      return '<span class="risk-badge risk-critical">逾期未接收</span>';
    }
    if (inbound.is_after_cutoff) {
      return '<span class="risk-badge risk-attention">停止收货日后</span>';
    }
    if (Number(inbound.planning_qty || 0) <= 0) {
      return '<span class="issue-chip">未计入预测</span>';
    }
    return '<span class="risk-badge risk-healthy">参与预测</span>';
  };
  const inboundRows = activeInbounds.length
    ? activeInbounds.map((inbound) => `
      <tr>
        <td><strong>${escapeHtml(inbound.cargo_code || "—")}</strong></td>
        <td class="number">${formatQty(inbound.remaining_qty)}</td>
        <td class="number">${formatQty(inbound.planning_qty)}</td>
        <td>${formatDate(inbound.eta_date)}</td>
        <td>${inboundStatus(inbound)}</td>
        <td>${escapeHtml(inbound.carrier || "—")}<small class="block-muted">${escapeHtml(inbound.tracking_number || "缺跟踪号")}</small></td>
      </tr>`).join("")
    : `<tr><td class="empty-row compact-empty" colspan="6">当前没有尚未入库的IBR</td></tr>`;
  const urgentFormula = enabledUrgentChannels.map((channel) => {
    const plan = item.channel_plans.find((candidate) => candidate.key === channel.key);
    return `<div class="formula-row"><span>${channel.label}需要发多少</span><code>${formatDate(item.planned_dispatch_date)}计划发货；最慢运输${formatDecimal(plan?.transit_max_days)}天 + 安全${formatDecimal(plan?.safety_days)}天 + 频率${formatDecimal(plan?.frequency_days)}天，最终预计${formatDate(plan?.arrival_date)}到货；按到货顺序只补到下一渠道到货前的缺口</code><strong>${formatQty(channelQuantities[channel.key].suggested)}件</strong></div>`;
  }).join("");
  const bridgeResult = channelResultParts.length
    ? channelResultParts.join(" → ")
    : "当前无需安排渠道";
  const groupMemberRows = (item.group_members || []).map((member) => `
    <tr>
      <td><strong>${escapeHtml(member.msku)}</strong></td>
      <td class="number">${formatDecimal(member.avg_7, 2)}</td>
      <td class="number">${formatDecimal(member.avg_14, 2)}</td>
      <td class="number">${formatDecimal(member.avg_30, 2)}</td>
      <td class="number">${formatQty(member.fbt_total)}</td>
      <td class="number">${formatQty(member.fbt_sellable)}</td>
      <td class="number">${formatQty(member.fbt_in_transit)}</td>
    </tr>`).join("");
  const productGroupPanel = item.is_grouped ? `
    <section class="product-group-panel">
      <div class="product-group-heading">
        <div>
          <span>合并商品组</span>
          <strong>${escapeHtml(item.canonical_msku)}</strong>
          <p>销量、FBT库存和IBR先合并，再统一计算一次发货与备货建议。</p>
        </div>
        <div class="product-status-actions">
          <label class="control">
            <span>执行MSKU</span>
            <select id="productGroupExecutionMsku">
              ${productMemberMskus(item).map((msku) => `<option value="${escapeHtml(msku)}" ${msku === item.execution_msku ? "selected" : ""}>${escapeHtml(msku)}</option>`).join("")}
            </select>
          </label>
          <button class="button button-secondary" id="saveProductGroupButton" type="button">
            <i data-lucide="save"></i><span>保存执行MSKU</span>
          </button>
        </div>
      </div>
      <div class="table-scroll compact-scroll">
        <table class="data-table product-group-table">
          <thead><tr><th>成员MSKU</th><th>7天日均</th><th>14天日均</th><th>30天日均</th><th>FBT库存</th><th>FBT可售</th><th>FBT在途</th></tr></thead>
          <tbody>${groupMemberRows}</tbody>
        </table>
      </div>
    </section>` : "";
  $("#drawerBody").innerHTML = `
    ${productGroupPanel}
    <section class="product-status-panel ${item.is_planning_excluded ? "is-excluded" : ""}">
      <div>
        <span>产品补货状态</span>
        <strong>${escapeHtml(planningStatusLabel)}</strong>
        <p>${escapeHtml(planningStatusHint)}</p>
      </div>
      <div class="product-status-actions">
        <label class="control">
          <span>状态</span>
          <select id="productPlanningStatus">
            <option value="active" ${item.planning_status === "active" ? "selected" : ""}>正常补货</option>
            <option value="clearance" ${item.planning_status === "clearance" ? "selected" : ""}>清仓</option>
            <option value="delisted" ${item.planning_status === "delisted" ? "selected" : ""}>下架</option>
          </select>
        </label>
        <button class="button button-secondary" id="saveProductStatusButton" type="button">
          <i data-lucide="tag"></i><span>保存状态</span>
        </button>
      </div>
    </section>
    <section class="detail-metrics">
      ${metricBox("动态日均", `${formatDecimal(item.dynamic_daily, 2)}件`, "系统")}
      ${metricBox("FBT库存", `${formatQty(item.fbt_total)}件`, "领星·已入仓")}
      ${metricBox("FBT可售", `${formatQty(item.fbt_sellable)}件`, "领星·已入仓可售")}
      ${metricBox("FBT在途", `${formatQty(item.fbt_in_transit)}件`, "领星·未入仓")}
      ${metricBox("有ETA在途", `${formatQty(item.dated_inbound_qty)}件`, "IBR台账")}
      ${metricBox("未排期在途", `${formatQty(item.unplaced_in_transit_qty)}件`, "待补ETA")}
      ${metricBox("当前可售覆盖", item.sellable_coverage_days === null ? "无销量" : `${formatDecimal(item.sellable_coverage_days)}天`, "FBT可售 ÷ 动态日均")}
      ${metricBox("预计断货", formatDate(item.stockout_date), "含往期IBR")}
    </section>
    <div class="detail-grid">
      <section class="panel forecast-panel">
        <div class="panel-heading">
          <div><h3>预计可售库存</h3><p id="forecastModeHint">在包含所选计算模式和安全缓冲后的最终预计到货日增加库存</p></div>
        </div>
        ${renderChannelTimeline(detail)}
        <div class="forecast-chart" id="forecastChart"></div>
      </section>
      <section class="panel recommendation-panel">
        <div class="panel-heading"><div><h3>系统建议</h3><p>本次计划${formatDate(item.planned_dispatch_date)}发货，买货看下一周计划</p></div></div>
        <div class="recommendation-list">
          ${urgentRecommendations}
          ${regularRecommendations}
          <div class="recommendation-item"><span>下次理论买货</span><strong>${formatQty(item.next_buy_gap)}</strong></div>
        </div>
        <div class="formula-ledger">
          <div class="formula-row"><span>每天预计卖出</span><code>近7日均销×50% + 近14日均销×30% + 近30日均销×20%</code><strong>${formatDecimal(item.dynamic_daily, 2)}件/天</strong></div>
          <div class="formula-row"><span>现在一共有多少货</span><code>FBT已入仓 ${formatQty(item.fbt_total)} + FBT在途 ${formatQty(item.fbt_in_transit)} + 已发未同步 ${formatQty(item.executed_unsynced_qty)}</code><strong>${formatQty(item.inventory_position)}件</strong></div>
          ${urgentFormula}
          <div class="formula-row"><span>近期总量够不够</span><code>${escapeHtml(item.regular_fastest_channel_label)}目标覆盖 ${formatDecimal(item.normal_target_coverage_days)} 天，需要 ${formatQty(item.normal_target_units)} 件 - 窗口内可用 ${formatQty(item.normal_available)} 件</code><strong>${item.base_normal_qty > 0 ? `缺 ${formatQty(item.base_normal_qty)}件` : "总量够"}</strong></div>
          <div class="formula-row"><span>到货时间怎样计算</span><code>从本次计划发货日 ${formatDate(item.planned_dispatch_date)} 起算：${item.timing_mode === "precise" ? "最近可赶截单/开船日 + 最慢运输时效 + 安全天数；精确船期等待替代发货频率" : "最慢运输时效 + 安全天数 + 发货频率"}；安全天数已包含签收至FBT入库风险</code><strong>${item.timing_mode === "precise" ? "精准船期" : "安全 + 频率"}</strong></div>
          <div class="formula-row"><span>到货前会不会断货</span><code>从今天开始逐日扣减销量，并在每个IBR预计入库日增加库存；再和最快常规渠道 ${escapeHtml(item.regular_fastest_channel_label)} 的最终预计到货日 ${formatDate(fastestRegularPlan?.arrival_date)} 比较</code><strong>${timingRiskText}</strong></div>
          <div class="formula-row"><span>本次总共要发多少</span><code>近期防断货缺口 ${formatQty(item.base_normal_qty)}；旺季缺口 ${formatQty(item.current_gap)}（旺季基础${formatDecimal(item.current_seasonal_coverage_days, 4)}天 + 安全${formatDecimal(item.safety_buffer_days)}天 + 发货频率${formatDecimal(item.dispatch_interval_days)}天）；取较大值，再受加急渠道桥接和停止收货日限制</code><strong>${formatQty(plannedShipTotal)}件</strong></div>
          <div class="formula-row"><span>渠道怎样接力</span><code>按各渠道最终预计到货日从早到晚逐日模拟；较早渠道负责撑到下一次到货，最后一个可用渠道承担剩余旺季数量</code><strong>${bridgeResult}</strong></div>
          <div class="formula-row"><span>本次渠道结果</span><code>只在参数设置中已启用的渠道之间按最终预计到货日分配，不重复增加本次总建议量</code><strong>${channelResultText}</strong></div>
          <div class="formula-row"><span>下次还要买多少</span><code>下次目标 ${formatQty(item.next_target_units)} - 现有总货 ${formatQty(item.inventory_position)} - 本次建议发货 ${formatQty(plannedShipTotal)}</code><strong>${formatQty(item.next_buy_gap)}件</strong></div>
        </div>
        <div class="inbound-ledger">
          <div class="inbound-ledger-title"><strong>未入库IBR</strong><span>${planningInbounds.length} 批参与预测 / ${activeInbounds.length} 批未入库</span></div>
          <div class="table-scroll compact-scroll"><table class="data-table"><thead><tr><th>IBR</th><th>未入库</th><th>计入预测</th><th>预计FBT入库</th><th>状态</th><th>物流</th></tr></thead><tbody>${inboundRows}</tbody></table></div>
        </div>
        <div class="data-note">
          领星库存口径：FBT合计 ${formatQty(fbtAll)} 件 = 已入仓 ${formatQty(item.fbt_total)} 件 + 在途 ${formatQty(item.fbt_in_transit)} 件；其中可售 ${formatQty(item.fbt_sellable)} 件。${escapeHtml(detail.forecast.note)}
          ${(item.data_notes || []).length ? `<br><strong>本商品说明：</strong>${escapeHtml(item.data_notes.join("；"))}` : ""}
        </div>
      </section>
      <section class="panel decision-panel">
        <div class="panel-heading"><div><h3>人工复核</h3><p>买货量未扣本地仓和供应商未到，必须人工确认</p></div></div>
        <div class="scenario-planner">
          <div class="scenario-toolbar">
            <div>
              <strong>发货节点</strong>
              <span id="scenarioSummary"></span>
            </div>
            <div class="scenario-actions">
              <button class="button button-secondary" id="resetScenarioButton" type="button">
                <i data-lucide="rotate-ccw"></i><span>恢复系统方案</span>
              </button>
              <button class="button button-secondary" id="recalculateScenarioButton" type="button">
                <i data-lucide="calculator"></i><span>重新自动分配</span>
              </button>
              <button class="button button-primary" id="addScenarioNodeButton" type="button">
                <i data-lucide="plus"></i><span>新增发货节点</span>
              </button>
            </div>
          </div>
          <div id="scenarioNodeList" class="scenario-node-list"></div>
        </div>
        <div class="decision-grid">
          <label class="control"><span>最终买货量</span><input id="decisionBuy" type="number" min="0" value="${finalBuy}"></label>
          <label class="control"><span>已发未同步</span><input id="decisionUnsynced" type="number" min="0" value="${item.executed_unsynced_qty || 0}"></label>
          <label class="control"><span>复核状态</span><select id="decisionStatus"><option value="pending">待复核</option><option value="reviewed">已复核</option><option value="executed">已执行</option></select></label>
          <label class="control decision-note"><span>备注</span><textarea id="decisionNote" placeholder="记录调整原因">${escapeHtml(item.note || "")}</textarea></label>
        </div>
        <div class="decision-actions"><button class="button button-primary" id="saveDecisionButton" type="button"><i data-lucide="save"></i><span>保存复核结果</span></button></div>
      </section>
    </div>`;
  $("#decisionStatus").value = item.review_status || "pending";
  $("#saveDecisionButton").addEventListener("click", saveDecision);
  $("#addScenarioNodeButton").addEventListener("click", addScenarioNode);
  $("#recalculateScenarioButton").addEventListener("click", recalculateScenario);
  $("#resetScenarioButton").addEventListener("click", resetScenarioNodes);
  $("#saveProductStatusButton").addEventListener("click", saveProductPlanningStatus);
  $("#saveProductGroupButton")?.addEventListener("click", saveProductGroupExecution);
  $("#decisionUnsynced")?.addEventListener("change", scheduleScenarioRecalculation);
  renderScenarioPlanner();
  renderForecastChart(detail);
  icons();
}

function renderForecastChart(detail) {
  const item = detail.product;
  const forecast = detail.forecast;
  const previewChannels = (state.manualScenarioNodes || [])
    .map((node) => ({
      ...node,
      key: node.channel_key || node.key,
      label: node.label || channelInfo(node.channel_key || node.key).label,
      quantity: Math.max(0, Number(node.quantity || 0)),
      preview_date: node.planning_arrival_date || node.arrival_date,
    }))
    .filter((plan) => plan.quantity > 0);
  const hasManualPreview = Boolean(
    state.scenarioDirty
    || item.confirmed_scenario_nodes?.length,
  );
  const plannedSeries = forecast.baseline.map((baselineValue, index) => {
    const pointDate = forecast.dates[index];
    const addedQuantity = previewChannels.reduce(
      (sum, channel) => (
        pointDate >= channel.preview_date ? sum + channel.quantity : sum
      ),
      0,
    );
    return Number((Number(baselineValue) + addedQuantity).toFixed(2));
  });
  const plannedSeriesName = hasManualPreview
    ? "手动调整后预计库存"
    : "正式建议预计库存";
  $("#forecastModeHint").textContent = `${hasManualPreview ? "正在按手动调整数量实时预览；" : ""}橙线在包含所选计算模式和安全缓冲后的最终预计到货日增加库存`;
  $$("[data-channel-preview-quantity]").forEach((element) => {
    const quantity = previewChannels
      .filter((node) => node.key === element.dataset.channelPreviewQuantity)
      .reduce((sum, node) => sum + node.quantity, 0);
    element.textContent = `${formatQty(quantity)}件`;
  });
  const values = [...forecast.baseline, ...plannedSeries];
  const minValue = Math.min(0, ...values);
  const channelColors = {
    "往期IBR": "#16845b",
    "快递 IP": "#db2777",
    "空派 IE": "#7c3aed",
    "快船": "#0284c7",
    "普船卡派": "#0f766e",
    "COSCO慢船": "#ca8a04",
  };
  const arrivalColor = (arrival) => ({
    express: "#db2777",
    air: "#7c3aed",
    quick: "#0284c7",
    truck: "#0f766e",
    slow: "#ca8a04",
  }[arrival.channel_key || arrival.key] || channelColors[arrival.channel || arrival.label] || "#16845b");
  const displayArrivals = [
    ...forecast.arrivals.filter((arrival) => arrival.kind === "existing"),
    ...previewChannels.map((channel) => ({
      date: channel.preview_date,
      actual_date: channel.arrival_date,
      buffered_date: channel.planning_arrival_date,
      channel: channel.label,
      channel_key: channel.key,
      quantity: channel.quantity,
      kind: "planned",
    })),
  ];
  const groupedArrivals = Object.values(displayArrivals.reduce((groups, arrival) => {
    const key = `${arrival.kind}|${arrival.date}|${arrival.channel}`;
    if (!groups[key]) groups[key] = { ...arrival, quantity: 0, count: 0 };
    groups[key].quantity += Number(arrival.quantity || 0);
    groups[key].count += 1;
    return groups;
  }, {}));
  const existingArrivalPoints = groupedArrivals.filter((arrival) => arrival.kind === "existing").map((arrival) => ({
    name: arrival.kind === "existing"
      ? `${arrival.count}批往期IBR +${arrival.quantity}`
      : `${arrival.channel} +${arrival.quantity}`,
    coord: [
      arrival.date,
      forecast.baseline[forecast.dates.indexOf(arrival.date)],
    ],
    value: `+${formatQty(arrival.quantity)}`,
    symbol: "pin",
    symbolSize: 42,
    itemStyle: { color: arrivalColor(arrival) },
  }));
  const plannedArrivalPoints = groupedArrivals.filter((arrival) => arrival.kind === "planned").map((arrival) => ({
    name: `${arrival.channel} +${arrival.quantity}`,
    coord: [
      arrival.date,
      plannedSeries[forecast.dates.indexOf(arrival.date)],
    ],
    value: `+${formatQty(arrival.quantity)}`,
    symbol: "pin",
    symbolSize: 44,
    itemStyle: { color: arrivalColor(arrival) },
  }));
  const stockoutPoints = (series, label) => series.flatMap((value, index) => (
    value <= 0 && (index === 0 || series[index - 1] > 0)
      ? [{
        name: `${label}断货`,
        coord: [forecast.dates[index], value],
        value: "断货",
        symbol: "circle",
        symbolSize: 10,
        itemStyle: { color: "#dc2626", borderColor: "#fff", borderWidth: 2 },
        label: { show: true, formatter: "断货", position: "top", color: "#b91c1c", fontSize: 10 },
      }]
      : []
  ));
  const arrivalLabelLaneDates = [];
  const plannedArrivalLines = groupedArrivals
    .filter((arrival) => arrival.kind === "planned")
    .sort((left, right) => left.date.localeCompare(right.date))
    .map((arrival) => {
      const arrivalTime = new Date(`${arrival.date}T00:00:00`).getTime();
      let lane = arrivalLabelLaneDates.findIndex(
        (dateTime) => (arrivalTime - dateTime) / 86400000 >= 30,
      );
      if (lane < 0) lane = arrivalLabelLaneDates.length;
      arrivalLabelLaneDates[lane] = arrivalTime;
      return {
        xAxis: arrival.date,
        name: `${arrival.channel}最终预计到货`,
        lineStyle: { color: arrivalColor(arrival), type: "dashed" },
        label: {
          formatter: `${arrival.channel}\n${formatDate(arrival.date)}到货`,
          color: arrivalColor(arrival),
          position: "insideEndTop",
          offset: [0, lane * 26],
          rotate: 0,
          backgroundColor: "rgba(255,255,255,.94)",
          borderRadius: 3,
          padding: [2, 4],
          fontSize: 9,
          lineHeight: 12,
        },
      };
    });
  const seasonalCoverageDate = addDays(
    forecast.dates[0],
    item.current_total_coverage_days,
  );
  const seasonalCoverageLine = {
    xAxis: seasonalCoverageDate,
    name: "旺季总量目标覆盖到",
    lineStyle: { color: "#7c3aed", type: "dotted", width: 2 },
    label: {
      formatter: `旺季总量覆盖到\n${formatDate(seasonalCoverageDate)}`,
      color: "#6d28d9",
    },
  };
  setChart("forecast", $("#forecastChart"), {
    animationDuration: 350,
    color: ["#1683ff", "#f97316", "#b45309"],
    grid: { left: 62, right: 32, top: 88, bottom: 62 },
    tooltip: {
      trigger: "axis",
      formatter(items) {
        const date = items[0]?.axisValue;
        const lines = items.map((entry) => `${entry.marker}${entry.seriesName}：${formatQty(entry.value)}件`);
        return `${formatDate(date)}<br/>${lines.join("<br/>")}`;
      },
    },
    legend: { top: 10, right: 20, data: ["现有方案预计库存", plannedSeriesName, "安全库存"] },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 10 }],
    xAxis: { type: "category", boundaryGap: false, data: forecast.dates, axisLabel: { formatter: (value) => `${new Date(`${value}T00:00:00`).getMonth() + 1}/${new Date(`${value}T00:00:00`).getDate()}` } },
    yAxis: { type: "value", name: "件", splitLine: { lineStyle: { color: "#edf0f3" } } },
    series: [
      {
        name: "现有方案预计库存",
        type: "line",
        showSymbol: false,
        data: forecast.baseline,
        lineStyle: { width: 2.2, color: "#1683ff" },
        itemStyle: { color: "#1683ff" },
        markPoint: {
          data: [...existingArrivalPoints, ...stockoutPoints(forecast.baseline, "现有方案")],
          label: { fontSize: 10 },
        },
        markArea: minValue < 0 ? { silent: true, itemStyle: { color: "rgba(201,54,54,.07)" }, data: [[{ yAxis: minValue }, { yAxis: 0 }]] } : undefined,
      },
      {
        name: plannedSeriesName,
        type: "line",
        showSymbol: false,
        data: plannedSeries,
        lineStyle: { width: 2.3, color: "#f97316" },
        itemStyle: { color: "#f97316" },
        markPoint: {
          data: [
            ...plannedArrivalPoints,
            ...stockoutPoints(plannedSeries, "补货后"),
          ],
          label: { fontSize: 10 },
        },
        markLine: {
          symbol: "none",
          label: { fontSize: 10 },
          data: [
            ...plannedArrivalLines,
            seasonalCoverageLine,
            ...(forecast.next_review_date ? [{
              xAxis: forecast.next_review_date,
              name: "下次复算",
              lineStyle: { color: "#64748b", type: "dotted" },
              label: {
                formatter: "下次复算",
                color: "#64748b",
                position: "insideStartBottom",
                rotate: 0,
                backgroundColor: "rgba(255,255,255,.92)",
                padding: [2, 4],
              },
            }] : []),
            { xAxis: forecast.cutoff_date, name: "停止收货", lineStyle: { color: "#c93636", type: "dashed" }, label: { formatter: "停止收货" } },
            { yAxis: 0, lineStyle: { color: "#c93636" }, label: { formatter: "断货线" } },
          ],
        },
      },
      { name: "安全库存", type: "line", showSymbol: false, data: forecast.safety, lineStyle: { width: 1, type: "dotted", color: "#b45309" } },
    ],
  });
}

async function saveProductGroupExecution() {
  const item = state.currentDetail?.product;
  const executionMsku = $("#productGroupExecutionMsku")?.value;
  if (!item?.is_grouped || !executionMsku) return;
  try {
    await api("/api/product-group", {
      method: "POST",
      body: JSON.stringify({
        store_id: item.store_id,
        canonical_msku: item.canonical_msku,
        execution_msku: executionMsku,
      }),
    });
    state.purchasePlan = null;
    showToast(`执行MSKU已改为 ${executionMsku}`);
    await loadDashboard($("#asOfInput").value);
    await openDetail(item.store_id, item.canonical_msku);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveProductPlanningStatus() {
  const item = state.currentDetail?.product;
  if (!item) return;
  const status = $("#productPlanningStatus").value;
  const [label] = planningStatusInfo(status);
  try {
    await api("/api/product-status", {
      method: "POST",
      body: JSON.stringify({
        store_id: item.store_id,
        msku: item.msku,
        status,
      }),
    });
    state.purchasePlan = null;
    showToast(`产品已标记为${label}`);
    await loadDashboard($("#asOfInput").value);
    await openDetail(item.store_id, item.canonical_msku || item.msku);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveDecision() {
  const detail = state.currentDetail;
  const item = detail.product;
  const scenarioNodes = (state.manualScenarioNodes || []).map((node) => ({
    id: node.id,
    channel_key: node.channel_key || node.key,
    label: node.label || channelInfo(node.channel_key || node.key).label,
    dispatch_date: node.dispatch_date || node.planned_dispatch_date,
    planning_arrival_date: node.planning_arrival_date || node.arrival_date,
    arrival_date: node.planning_arrival_date || node.arrival_date,
    manual_arrival_override: Boolean(node.manual_arrival_override),
    eligible_before_cutoff: node.eligible_before_cutoff !== false,
    quantity: Math.max(0, Number(node.quantity || 0)),
    quantity_locked: Boolean(node.quantity_locked),
    auto_generated: Boolean(node.auto_generated),
  }));
  const channelTotal = (key) => scenarioNodes
    .filter((node) => node.channel_key === key)
    .reduce((sum, node) => sum + node.quantity, 0);
  const payload = {
    msku: item.decision_msku || item.canonical_msku || item.msku,
    store_id: item.store_id,
    week_date: detail.schedule_context.current.week_date,
    air_enabled: item.air_enabled,
    channel_signature: item.decision_signature || item.channel_signature,
    timing_mode: item.timing_mode,
    air_service: item.air_service,
    confirmed_express_qty: itemChannelEnabled(item, "express") ? channelTotal("express") : null,
    confirmed_air_qty: itemChannelEnabled(item, "air") ? channelTotal("air") : null,
    confirmed_quick_qty: itemChannelEnabled(item, "quick") ? channelTotal("quick") : null,
    confirmed_truck_qty: itemChannelEnabled(item, "truck") ? channelTotal("truck") : null,
    confirmed_slow_qty: itemChannelEnabled(item, "slow") ? channelTotal("slow") : null,
    scenario_nodes: scenarioNodes,
    final_buy_qty: Number($("#decisionBuy").value || 0),
    executed_unsynced_qty: Number($("#decisionUnsynced").value || 0),
    review_status: $("#decisionStatus").value,
    note: $("#decisionNote").value.trim(),
  };
  try {
    await api("/api/decision", { method: "POST", body: JSON.stringify(payload) });
    showToast("人工复核结果已保存");
    await loadDashboard($("#asOfInput").value);
    await openDetail(item.store_id, item.canonical_msku || item.msku);
  } catch (error) {
    showToast(error.message, true);
  }
}

function closeDrawer() {
  $("#detailDrawer").classList.remove("is-open");
  $("#detailDrawer").setAttribute("aria-hidden", "true");
  setTimeout(() => { $("#drawerBackdrop").hidden = true; }, 180);
}

function showPage(page) {
  state.activePage = page;
  $$(".page").forEach((element) => element.classList.toggle("is-active", element.id === `${page}Page`));
  $$(".nav-button").forEach((button) => button.classList.toggle("is-active", button.dataset.page === page));
  if (page === "schedule") setTimeout(renderSchedule, 20);
  if (page === "product-status") renderProductStatusPage();
  if (page === "purchase") {
    if (state.purchasePlan) renderPurchasePlan();
    else loadPurchasePlan($("#asOfInput").value).catch((error) => showToast(error.message, true));
  }
  if (page === "shipments") {
    if (state.shipmentData) renderShipments();
    else loadShipments($("#asOfInput").value);
  }
}

function bindEvents() {
  $$(".nav-button").forEach((button) => button.addEventListener("click", () => showPage(button.dataset.page)));
  $("#pullButton").addEventListener("click", pullLatest);
  $("#emptyPullButton").addEventListener("click", pullLatest);
  $("#exportButton").addEventListener("click", () => {
    if (!state.dashboard) return showToast("请先拉取领星数据", true);
    window.location.href = `/api/export?as_of=${encodeURIComponent($("#asOfInput").value)}`;
  });
  $("#asOfInput").addEventListener("change", () => loadDashboard($("#asOfInput").value));
  $("#storeFilter").addEventListener("change", renderTable);
  $("#riskFilter").addEventListener("change", renderTable);
  $("#searchInput").addEventListener("input", renderTable);
  $("#shipmentStatusFilter").addEventListener("change", renderShipments);
  $("#shipmentSearchInput").addEventListener("input", renderShipments);
  $("#arrivalImportButton").addEventListener("click", () => $("#arrivalImportInput").click());
  $("#arrivalImportInput").addEventListener("change", (event) => importArrivalTracking(event.target.files?.[0]));
  $("#arrivalExportButton").addEventListener("click", () => {
    window.location.href = `/api/arrival-tracking/export?as_of=${encodeURIComponent($("#asOfInput").value)}`;
  });
  $("#purchaseCompletedMonth").addEventListener("change", (event) => {
    updatePurchasePlanMonth(Number(event.target.value));
    renderPurchasePlan();
  });
  $("#purchaseSearchInput").addEventListener("input", renderPurchaseTable);
  $("#productStatusStoreFilter").addEventListener("change", renderProductStatusPage);
  $("#productStatusFilter").addEventListener("change", renderProductStatusPage);
  $("#productStatusSearchInput").addEventListener("input", renderProductStatusPage);
  $("#productStatusSelectAll").addEventListener("change", (event) => {
    filteredProductStatusItems().forEach((item) => {
      const key = productIdentity(item);
      if (event.target.checked) state.productStatusSelection.add(key);
      else state.productStatusSelection.delete(key);
    });
    renderProductStatusPage();
  });
  $("#productStatusTableBody").addEventListener("change", (event) => {
    const checkbox = event.target.closest(".product-status-checkbox");
    if (checkbox) {
      if (checkbox.checked) {
        state.productStatusSelection.add(checkbox.dataset.productKey);
      } else {
        state.productStatusSelection.delete(checkbox.dataset.productKey);
      }
      updateProductStatusSelectionState();
      return;
    }
    const select = event.target.closest(".product-status-row-select");
    if (select) {
      const [label] = planningStatusInfo(select.value);
      saveProductStatusItems(
        [{
          store_id: select.dataset.storeId,
          msku: select.dataset.msku,
          status: select.value,
        }],
        `已将 ${select.dataset.msku} 标记为${label}`,
      );
    }
  });
  $("#applyProductStatusButton").addEventListener("click", applyProductStatusBatch);
  $("#savePurchaseButton").addEventListener("click", () => {
    savePurchasePlan().catch((error) => showToast(error.message, true));
  });
  $("#exportPurchaseButton").addEventListener("click", exportPurchasePlan);
  $("#purchaseTableBody").addEventListener("input", (event) => {
    const input = event.target.closest("[data-purchase-field]");
    if (input) updatePurchaseInput(input);
  });
  $("#purchaseTableBody").addEventListener("click", (event) => {
    const button = event.target.closest("[data-purchase-reset]");
    if (button) resetPurchaseInput(button);
  });
  $("#shipmentTableBody").addEventListener("click", (event) => {
    const button = event.target.closest(".shipment-edit-button");
    if (button) openShipmentDialog(button.dataset.cargo);
  });
  $("#shipmentForm").addEventListener("submit", (event) => {
    event.preventDefault();
    if (event.submitter?.value === "cancel") {
      $("#shipmentDialog").close();
      return;
    }
    saveShipmentOverride();
  });
  $("#reconciliationTableBody").addEventListener("click", (event) => {
    const button = event.target.closest(".alias-edit-button");
    if (button) openAliasDialog(button.dataset.item);
  });
  $("#aliasForm").addEventListener("submit", (event) => {
    event.preventDefault();
    if (event.submitter?.value === "cancel") {
      $("#aliasDialog").close();
      return;
    }
    saveProductAlias();
  });
  $("#viewTabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view]");
    if (!button) return;
    state.activeView = button.dataset.view;
    $$("#viewTabs button").forEach((item) => item.classList.toggle("is-active", item === button));
    renderTable();
  });
  $("#tableBody").addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-key]");
    if (!row) return;
    const separator = row.dataset.key.indexOf("|");
    openDetail(row.dataset.key.slice(0, separator), row.dataset.key.slice(separator + 1));
  });
  $("#saveScheduleButton").addEventListener("click", saveSchedule);
  $("#saveSettingsButton").addEventListener("click", saveSettings);
  [
    "#timingModeInput",
    "#expressMinInput", "#expressMaxInput", "#airMinInput", "#airMaxInput",
    "#quickMinInput", "#quickMaxInput", "#truckMinInput", "#truckMaxInput",
    "#slowMinInput", "#slowMaxInput",
    "#expressSafetyInput", "#expressFrequencyInput",
    "#airSafetyInput", "#airFrequencyInput",
    "#quickSafetyInput", "#quickFrequencyInput",
    "#truckSafetyInput", "#truckFrequencyInput",
    "#slowSafetyInput", "#slowFrequencyInput",
    "#weight7Input", "#weight14Input", "#weight30Input",
  ].forEach((selector) => $(selector).addEventListener("input", updateSettingsPreview));
  CHANNEL_UI.forEach((channel) => {
    $(`#${channel.key}ChannelEnabledInput`).addEventListener("change", updateSettingsPreview);
  });
  $("#closeDrawerButton").addEventListener("click", closeDrawer);
  $("#drawerBackdrop").addEventListener("click", closeDrawer);
  window.addEventListener("resize", () => Object.values(state.charts).forEach((chart) => chart.resize()));
  window.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
}

async function init() {
  icons();
  bindEvents();
  try {
    await loadDashboard();
  } catch (_) {
    // loadDashboard already reports the error.
  }
}

init();
