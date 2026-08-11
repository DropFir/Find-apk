const form = document.querySelector("#search-form");
const input = document.querySelector("#search-input");
const results = document.querySelector("#results");
const emptyState = document.querySelector("#empty-state");
const resultsHeading = document.querySelector("#results-heading");
const sectionKicker = document.querySelector("#section-kicker");
const resultCount = document.querySelector("#result-count");
const statusPill = document.querySelector("#status-pill");
const statusText = document.querySelector("#status-text");
const storagePill = document.querySelector("#storage-pill");
const storageText = document.querySelector("#storage-text");
const storageMeterFill = document.querySelector("#storage-meter-fill");
const queueForm = document.querySelector("#queue-form");
const keywordInput = document.querySelector("#keyword-input");
const queueAddButton = document.querySelector("#queue-add-button");
const queueMessage = document.querySelector("#queue-message");
const queueList = document.querySelector("#queue-list");
const queueWaitingCount = document.querySelector("#queue-waiting-count");
const queueProcessingCount = document.querySelector("#queue-processing-count");
const queueCompletedCount = document.querySelector("#queue-completed-count");
const queuePageSummary = document.querySelector("#queue-page-summary");
const queuePagePrev = document.querySelector("#queue-page-prev");
const queuePageNext = document.querySelector("#queue-page-next");
const notFoundList = document.querySelector("#notfound-list");
const notFoundMissingCount = document.querySelector("#notfound-missing-count");
const notFoundIosCount = document.querySelector("#notfound-ios-count");
const notFoundManualCount = document.querySelector("#notfound-manual-count");
const notFoundPaidCount = document.querySelector("#notfound-paid-count");
const notFoundPageSummary = document.querySelector("#notfound-page-summary");
const notFoundPagePrev = document.querySelector("#notfound-page-prev");
const notFoundPageNext = document.querySelector("#notfound-page-next");
const notFoundSearchForm = document.querySelector("#notfound-search-form");
const notFoundSearchInput = document.querySelector("#notfound-search-input");
const notFoundModeButtons = document.querySelectorAll("[data-notfound-mode]");
const cloudflareList = document.querySelector("#cloudflare-list");
const cloudflareTotalCount = document.querySelector("#cloudflare-total-count");
const cloudflareNavCount = document.querySelector("#cloudflare-nav-count");
const cloudflarePageSummary = document.querySelector("#cloudflare-page-summary");
const cloudflarePagePrev = document.querySelector("#cloudflare-page-prev");
const cloudflarePageNext = document.querySelector("#cloudflare-page-next");
const productionDate = document.querySelector("#production-date");
const productionTotalCount = document.querySelector("#production-total-count");
const productionTodayDetail = document.querySelector("#production-today-detail");
const productionYesterdayCount = document.querySelector(
  "#production-yesterday-count",
);
const productionYesterdayDetail = document.querySelector(
  "#production-yesterday-detail",
);
const productionLaneACount = document.querySelector("#production-lane-a-count");
const productionLaneBCount = document.querySelector("#production-lane-b-count");
const productionLaneAYesterday = document.querySelector(
  "#production-lane-a-yesterday",
);
const productionLaneBYesterday = document.querySelector(
  "#production-lane-b-yesterday",
);
const productionLaneADate = document.querySelector("#production-lane-a-date");
const productionLaneBDate = document.querySelector("#production-lane-b-date");
const productionDateStepButtons = document.querySelectorAll(
  "[data-production-date-step]",
);
const productionMonitorState = document.querySelector(
  "#production-monitor-state",
);
const productionCleanupButton = document.querySelector(
  "#production-cleanup-button",
);
const productionStorageSpace = document.querySelector(
  "#production-storage-space",
);
const productionStorageDetail = document.querySelector(
  "#production-storage-detail",
);
const productionTemporaryBundles = document.querySelector(
  "#production-temporary-bundles",
);
const codexPanel = document.querySelector("#codex-view");
const codexSettingsForm = document.querySelector("#codex-settings-form");
const codexEnabled = document.querySelector("#codex-enabled");
const codexModel = document.querySelector("#codex-model");
const codexEffort = document.querySelector("#codex-effort");
const codexInterval = document.querySelector("#codex-interval");
const codexBatchSize = document.querySelector("#codex-batch-size");
const codexWorkerCount = document.querySelector("#codex-worker-count");
const codexWorkers = document.querySelector("#codex-workers");
const codexSaveButton = document.querySelector("#codex-save-button");
const codexRunButton = document.querySelector("#codex-run-button");
const codexStopButton = document.querySelector("#codex-stop-button");
const codexEnabledState = document.querySelector("#codex-enabled-state");
const codexNextRun = document.querySelector("#codex-next-run");
const codexRunningCount = document.querySelector("#codex-running-count");
const codexBatchSummary = document.querySelector("#codex-batch-summary");
const codexServerState = document.querySelector("#codex-server-state");
const codexMessage = document.querySelector("#codex-message");
const browserWorkerState = document.querySelector("#browser-worker-state");
const browserWorkerDetail = document.querySelector("#browser-worker-detail");
const productionLaneA = document.querySelector("#production-lane-a");
const productionLaneB = document.querySelector("#production-lane-b");
const productionPanel = document.querySelector("#production-view");
const navTabs = document.querySelectorAll("[data-view]");
const viewPanels = document.querySelectorAll("[data-view-panel]");
const viewSwitches = document.querySelectorAll("[data-switch-view]");
const pageTitle = document.querySelector("#page-title");
const pageDescription = document.querySelector("#page-description");
const pageBreadcrumb = document.querySelector("#page-breadcrumb");
const queueNavCount = document.querySelector("#queue-nav-count");
const notFoundNavCount = document.querySelector("#notfound-nav-count");
const productionNavCount = document.querySelector("#production-nav-count");
const libraryTotalCount = document.querySelector("#library-total-count");
const sidebarToggle = document.querySelector("#sidebar-toggle");
const errorApkNavCount = document.querySelector("#error-apk-nav-count");
const errorApkTotalCount = document.querySelector("#error-apk-total-count");
const errorApkForm = document.querySelector("#error-apk-form");
const errorApkFileInput = document.querySelector("#error-apk-file-input");
const errorApkDropzone = document.querySelector("#error-apk-dropzone");
const errorApkSelected = document.querySelector("#error-apk-selected");
const errorApkReason = document.querySelector("#error-apk-reason");
const errorApkSubmit = document.querySelector("#error-apk-submit");
const errorApkMessage = document.querySelector("#error-apk-message");
const errorApkList = document.querySelector("#error-apk-list");

let debounceTimer;
let activeRequest = 0;
let lastKnownCount = -1;
let queueRequestActive = false;
let latestQueueSnapshot = null;
let queuePage = 1;
let notFoundRequestActive = false;
let latestNotFoundSnapshot = null;
let notFoundPage = 1;
let notFoundSearchTimer;
let notFoundQuery = "";
let notFoundMode = "pending";
let notFoundEditingJobId = null;
let cloudflareRequestActive = false;
let latestCloudflareSnapshot = null;
let cloudflarePage = 1;
let productionRequestActive = false;
let productionCleanupActive = false;
let codexRequestActive = false;
let codexSettingsLoaded = false;
let codexSettingsDirty = false;
let errorApkRequestActive = false;
let selectedErrorApkFile = null;
let latestProductionFingerprint = "";
const productionLaneDates = { 1: "", 2: "" };
const productionDownloadPending = new Map();
const queuePageSize = 20;
const notFoundPageSize = 20;
const cloudflarePageSize = 20;

const viewMetadata = {
  library: {
    title: "APK 搜索",
    description: "搜索并下载完整交付包，内含安装包、图标、开发者和来源。",
    breadcrumb: "文件库",
  },
  apkba: {
    title: "APKBA 制作站",
    description: "直接查看 APKBA 制作进度、任务状态和错误信息。",
    breadcrumb: "制作站",
  },
  queue: {
    title: "关键词任务",
    description: "提交新的 APK 关键词，并查看 Agent 的查找进度。",
    breadcrumb: "任务队列",
  },
  production: {
    title: "每日制作队列",
    description: "两人分别负责 A、B 两组；下载后共享变灰，未完成项目自动顺延。",
    breadcrumb: "制作队列",
  },
  codex: {
    title: "Codex 调度",
    description: "设置模型与频率，让本机 Codex 自动领取关键词任务。",
    breadcrumb: "Codex 调度",
  },
  "error-apk": {
    title: "错误 APK",
    description: "上传出现问题的完整 ZIP，并留下具体错误原因。",
    breadcrumb: "问题包",
  },
  cloudflare: {
    title: "Cloudflare 拦截",
    description: "查看已经确认精确页面、但仍等待验证或浏览器下载的 APK。",
    breadcrumb: "受阻候选",
  },
  notfound: {
    title: "找不到 / 已跳过",
    description: "查看无结果跳过、付费跳过的关键词和具体原因。",
    breadcrumb: "跳过记录",
  },
};

function setSidebarCollapsed(collapsed, { remember = true } = {}) {
  document.body.classList.toggle("is-sidebar-collapsed", collapsed);
  sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
  sidebarToggle.setAttribute(
    "aria-label",
    collapsed ? "展开左侧栏" : "收起左侧栏",
  );
  sidebarToggle.title = collapsed ? "展开左侧栏" : "收起左侧栏";
  navTabs.forEach((tab) => {
    const label = tab.querySelector(".nav-copy strong")?.textContent?.trim();
    tab.title = collapsed && label ? label : "";
  });
  if (remember) {
    try {
      localStorage.setItem(
        "find-apk-sidebar-collapsed",
        collapsed ? "1" : "0",
      );
    } catch {
      // The sidebar still changes when storage is unavailable.
    }
  }
}

function switchView(viewName, { remember = true } = {}) {
  const metadata = viewMetadata[viewName];
  if (!metadata) return;

  document.body.classList.toggle(
    "is-production-view",
    viewName === "production",
  );
  document.body.classList.toggle(
    "is-apkba-view",
    viewName === "apkba",
  );
  document.documentElement.classList.toggle(
    "is-apkba-view",
    viewName === "apkba",
  );
  document.body.classList.toggle(
    "is-notfound-view",
    viewName === "notfound",
  );
  document.documentElement.classList.toggle(
    "is-notfound-view",
    viewName === "notfound",
  );
  document.body.classList.toggle(
    "is-cloudflare-view",
    viewName === "cloudflare",
  );
  document.documentElement.classList.toggle(
    "is-cloudflare-view",
    viewName === "cloudflare",
  );
  navTabs.forEach((tab) => {
    const active = tab.dataset.view === viewName;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  viewPanels.forEach((panel) => {
    const active = panel.dataset.viewPanel === viewName;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });

  pageTitle.textContent = metadata.title;
  pageDescription.textContent = metadata.description;
  pageBreadcrumb.textContent = metadata.breadcrumb;

  if (remember) {
    try {
      localStorage.setItem("find-apk-admin-view", viewName);
    } catch {
      // The view still switches when storage is unavailable.
    }
  }
  if (viewName === "queue") loadQueue();
  if (viewName === "production") loadProduction();
  if (viewName === "codex") {
    loadCodexController();
    loadBrowserWorker();
  }
  if (viewName === "error-apk") loadErrorApks();
  if (viewName === "cloudflare") loadCloudflareBlocked();
  if (viewName === "notfound") loadNotFound();
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function createAppIcon(item, className, size) {
  const icon = createElement("img", className);
  icon.src = item.icon_url;
  icon.alt = "";
  icon.loading = "lazy";
  icon.width = size;
  icon.height = size;
  icon.addEventListener(
    "error",
    () => {
      const cleared = createElement(
        "span",
        `${className} icon-cleared`,
        "已清除",
      );
      cleared.setAttribute("aria-label", "本机文件已清除");
      icon.replaceWith(cleared);
    },
    { once: true },
  );
  return icon;
}

function createCard(item) {
  const card = createElement("article", "result-card");
  const top = createElement("div", "card-top");
  const icon = createAppIcon(item, "app-icon", 62);
  const badge = createElement("span", "format-badge", item.package_format);
  top.append(icon, badge);

  const body = createElement("div", "card-body");
  const title = createElement("h3", "", item.keyword);
  title.title = item.keyword;
  const developer = createElement("p", "developer", item.developer);
  developer.title = item.developer;
  body.append(title, developer);

  const footer = createElement("div", "card-footer");
  const metadata = createElement("div", "file-meta");
  const filename = createElement("span", "file-name", item.package_name);
  filename.title = item.package_name;
  const detail = createElement(
    "span",
    "file-detail",
    `${item.package_size_label} · ${item.date}`,
  );
  metadata.append(filename, detail);

  const download = createElement("a", "download-button", "下载压缩包");
  download.href = item.download_url;
  download.setAttribute("download", `${item.directory_name}.zip`);
  download.setAttribute(
    "aria-label",
    `下载 ${item.keyword} 完整交付压缩包`,
  );
  footer.append(metadata, download);

  card.append(top, body, footer);
  return card;
}

function formatProductionDate(value) {
  if (!value) return "—";
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  }).format(parsed);
}

function productionPendingState(item) {
  if (item.queue_status === "external_completed") {
    productionDownloadPending.delete(item.delivery_key);
    return "external";
  }
  if (item.downloaded) {
    productionDownloadPending.delete(item.delivery_key);
    return "downloaded";
  }
  const startedAt = productionDownloadPending.get(item.delivery_key);
  if (!startedAt) {
    return item.queue_status === "rolled" ? "rolled" : "ready";
  }
  if (Date.now() - startedAt > 30000) {
    productionDownloadPending.delete(item.delivery_key);
    return item.queue_status === "rolled" ? "rolled" : "ready";
  }
  return "pending";
}

function createProductionItem(item) {
  const state = productionPendingState(item);
  const card = createElement(
    "article",
    `production-item${state === "downloaded" || state === "pending" || state === "external" ? " is-downloaded" : ""}${state === "rolled" ? " is-rolled" : ""}${state === "external" ? " is-external" : ""}`,
  );
  card.dataset.deliveryKey = item.delivery_key;

  const icon = createAppIcon(item, "production-icon", 44);

  const copy = createElement("div", "production-item-copy");
  const titleRow = createElement("div", "production-item-title");
  const title = createElement("h4", "", item.keyword);
  title.title = item.keyword;
  const status = createElement(
    "span",
    "production-item-status",
    state === "downloaded"
      ? "已领取，可重新下载"
      : state === "external"
        ? "网站已完成"
      : state === "pending"
        ? "正在准备"
        : state === "rolled"
          ? "未完成，已顺延"
        : "待下载",
  );
  titleRow.append(title, status);
  const developer = createElement("p", "", item.developer);
  developer.title = item.developer;
  const meta = createElement(
    "p",
    "production-item-meta",
    `${item.package_format} · ${item.package_size_label} · 入库 ${item.date}`,
  );
  copy.append(titleRow, developer, meta);

  const download = createElement(
    "a",
    "production-download",
    state === "downloaded"
      ? "重新下载"
      : state === "external"
        ? "重新下载"
        : state === "pending"
          ? "准备中"
          : "下载",
  );
  if (state !== "pending") {
    download.href = item.download_url;
    download.setAttribute("download", `${item.keyword}.zip`);
    download.setAttribute(
      "aria-label",
      `${state === "downloaded" ? "重新下载" : "下载"} ${item.keyword} 完整交付压缩包`,
    );
    download.addEventListener("click", () => {
      productionDownloadPending.set(item.delivery_key, Date.now());
      card.classList.add("is-downloaded");
      status.textContent = "正在准备";
      download.textContent = "准备中";
    });
  }

  card.append(icon, copy, download);
  return card;
}

function renderProductionLane(container, items) {
  container.replaceChildren();
  if (!items.length) {
    container.append(
      createElement("p", "production-placeholder", "这一组今天没有任务"),
    );
    return;
  }
  const fragment = document.createDocumentFragment();
  items.forEach((item) => fragment.append(createProductionItem(item)));
  container.append(fragment);
}

function renderProduction(snapshot) {
  const laneA = snapshot.lanes?.["1"] || [];
  const laneB = snapshot.lanes?.["2"] || [];
  const today = snapshot.today || {};
  const yesterday = snapshot.yesterday || {};
  const todayCounts = today.counts || {};
  const yesterdayCounts = yesterday.counts || {};
  const remaining = Math.max(0, (today.total || 0) - (today.downloaded || 0));

  productionDate.textContent = formatProductionDate(snapshot.date);
  productionTotalCount.textContent = today.total || 0;
  productionTodayDetail.textContent = `已下载 ${today.downloaded || 0} · 未完成 ${remaining}`;
  productionYesterdayCount.textContent = yesterday.total || 0;
  productionYesterdayDetail.textContent =
    `A 组 ${yesterdayCounts["1"] || 0} · B 组 ${yesterdayCounts["2"] || 0}`;
  productionLaneAYesterday.textContent = yesterdayCounts["1"] || 0;
  productionLaneBYesterday.textContent = yesterdayCounts["2"] || 0;
  productionLaneACount.textContent = laneA.length;
  productionLaneBCount.textContent = laneB.length;
  productionNavCount.textContent = remaining;
  productionNavCount.hidden = remaining === 0;
  const storage = snapshot.storage || {};
  const removableDirectories = Number(storage.directories) || 0;
  const removableBytes = Number(storage.bytes) || 0;
  const temporaryFiles = Number(storage.temporary_files) || 0;
  const temporaryBytes = Number(storage.temporary_bytes) || 0;
  productionStorageSpace.textContent = removableDirectories
    ? `${formatUploadSize(removableBytes)} 可释放`
    : "暂无可释放空间";
  productionStorageDetail.textContent = removableDirectories
    ? `${removableDirectories} 个已领取交付目录仍在本机；清理后不能再从本机下载。`
    : "已领取交付包没有占用本机空间。";
  productionTemporaryBundles.textContent = temporaryFiles
    ? `临时下载 ZIP：${temporaryFiles} 个 · ${formatUploadSize(temporaryBytes)}（传输完成会自动删除）`
    : "临时下载 ZIP：0 B（传输完成会自动删除）";
  productionCleanupButton.disabled =
    productionCleanupActive || removableDirectories === 0;
  productionCleanupButton.textContent = removableDirectories
    ? `释放本机空间 · ${formatUploadSize(removableBytes)}`
    : "没有可释放的交付包";
  const monitor = snapshot.monitor || {};
  if (monitor.last_error) {
    productionMonitorState.textContent = "制作网站暂时无法连接";
  } else if (monitor.last_public_error) {
    productionMonitorState.textContent = "制作监控正常 · 公开站等待重试";
  } else if (monitor.last_checked_at) {
    productionMonitorState.textContent = "制作监控 30 秒 · 公开站 5 分钟";
  } else {
    productionMonitorState.textContent = "正在连接制作网站…";
  }
  productionLaneDates[1] = snapshot.lane_dates?.["1"] || snapshot.date;
  productionLaneDates[2] = snapshot.lane_dates?.["2"] || snapshot.date;
  productionLaneADate.value = productionLaneDates[1];
  productionLaneBDate.value = productionLaneDates[2];
  productionLaneADate.max = snapshot.date;
  productionLaneBDate.max = snapshot.date;
  productionDateStepButtons.forEach((button) => {
    const lane = Number(button.dataset.productionDateStep);
    const direction = Number(button.dataset.direction);
    button.disabled =
      direction > 0 && productionLaneDates[lane] >= snapshot.date;
  });
  const fingerprint = [
    snapshot.lane_dates?.["1"],
    ...laneA,
    "|",
    snapshot.lane_dates?.["2"],
    ...laneB,
  ]
    .map((item) => {
      if (typeof item === "string") return item;
      return `${item.delivery_key}:${productionPendingState(item)}`;
    })
    .join(",");
  if (fingerprint !== latestProductionFingerprint) {
    latestProductionFingerprint = fingerprint;
    renderProductionLane(productionLaneA, laneA);
    renderProductionLane(productionLaneB, laneB);
  }
}

async function cleanupDownloadedProduction() {
  if (productionCleanupActive) return;
  productionCleanupActive = true;
  productionCleanupButton.disabled = true;
  productionCleanupButton.textContent = "正在统计…";
  try {
    const previewResponse = await fetch(
      "/api/production/cleanup-downloaded",
      { cache: "no-store" },
    );
    if (!previewResponse.ok) {
      throw new Error(`HTTP ${previewResponse.status}`);
    }
    const preview = await previewResponse.json();
    if (!preview.directories) {
      window.alert("当前没有占用本机空间的已领取交付包。");
      return;
    }
    const confirmed = window.confirm(
      `将永久删除本机 ${preview.directories} 个已领取交付目录，预计释放 ${formatUploadSize(preview.bytes)}。\n\n删除内容包含 APK/XAPK、图标和来源文件；制作网站、关键词记录、待下载及“网站已完成”条目不会受影响。删除后不能再从这台电脑下载这些包。\n\n确定释放空间吗？`,
    );
    if (!confirmed) return;

    productionCleanupButton.textContent = "正在删除…";
    const response = await fetch(
      "/api/production/cleanup-downloaded",
      { method: "DELETE" },
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    const failureDetail = payload.failed
      ? `，${payload.failed} 个目录删除失败`
      : "";
    window.alert(
      `已清理 ${payload.directories} 个本地交付目录，释放 ${formatUploadSize(payload.freed_bytes)}${failureDetail}。`,
    );
  } catch (error) {
    window.alert(`清理失败：${error.message}`);
  } finally {
    productionCleanupActive = false;
    await loadProduction();
  }
}

async function loadProduction() {
  if (!productionPanel.classList.contains("is-active")) return;
  if (productionRequestActive) return;
  productionRequestActive = true;
  try {
    const parameters = new URLSearchParams();
    if (productionLaneDates[1]) {
      parameters.set("lane_a_date", productionLaneDates[1]);
    }
    if (productionLaneDates[2]) {
      parameters.set("lane_b_date", productionLaneDates[2]);
    }
    const query = parameters.toString();
    const response = await fetch(`/api/production${query ? `?${query}` : ""}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderProduction(await response.json());
  } catch {
    productionLaneA.replaceChildren(
      createElement("p", "production-placeholder is-error", "制作队列暂时无法连接"),
    );
    productionLaneB.replaceChildren(
      createElement("p", "production-placeholder is-error", "制作队列暂时无法连接"),
    );
  } finally {
    productionRequestActive = false;
  }
}

function shiftProductionDate(lane, direction) {
  const value = productionLaneDates[lane];
  if (!value) return;
  const selected = new Date(`${value}T12:00:00`);
  selected.setDate(selected.getDate() + direction);
  const year = selected.getFullYear();
  const month = String(selected.getMonth() + 1).padStart(2, "0");
  const day = String(selected.getDate()).padStart(2, "0");
  productionLaneDates[lane] = `${year}-${month}-${day}`;
  latestProductionFingerprint = "";
  loadProduction();
}

function chooseProductionDate(lane, value) {
  if (!value) return;
  productionLaneDates[lane] = value;
  latestProductionFingerprint = "";
  loadProduction();
}

function renderItems(items, query) {
  results.replaceChildren();
  const searching = query.trim().length > 0;
  resultsHeading.textContent = searching ? `“${query.trim()}” 的结果` : "最近入库";
  sectionKicker.textContent = searching ? "SEARCH RESULTS" : "APK LIBRARY";
  resultCount.textContent = `${items.length} 个文件`;

  if (!items.length) {
    results.hidden = true;
    emptyState.hidden = false;
    return;
  }

  results.hidden = false;
  emptyState.hidden = true;
  const fragment = document.createDocumentFragment();
  items.forEach((item) => fragment.append(createCard(item)));
  results.append(fragment);
}

async function search(query = input.value) {
  const requestId = ++activeRequest;
  try {
    const response = await fetch(
      `/api/search?q=${encodeURIComponent(query)}&limit=100`,
      { headers: { Accept: "application/json" } },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (requestId !== activeRequest) return;
    renderItems(payload.items, query);
  } catch {
    if (requestId !== activeRequest) return;
    results.replaceChildren();
    results.hidden = true;
    emptyState.hidden = false;
    emptyState.querySelector("h3").textContent = "连接暂时不可用";
    emptyState.querySelector("p").textContent = "请确认 Find APK 服务仍在运行。";
  }
}

async function updateStatus() {
  try {
    const response = await fetch("/api/status", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) return;
    const status = await response.json();
    statusPill.classList.toggle("is-scanning", status.scanning);
    libraryTotalCount.textContent = status.count;
    if (status.storage) {
      const free = formatStorageSize(status.storage.free);
      const total = formatStorageSize(status.storage.total);
      const percent = Math.min(100, Math.max(0, status.storage.percent || 0));
      storageText.textContent = `剩余 ${free} / ${total}`;
      storageMeterFill.style.width = `${percent}%`;
      storagePill.classList.toggle(
        "is-critical",
        status.storage.free < 5 * 1024 ** 3 || percent >= 95,
      );
      storagePill.title = `已使用 ${percent.toFixed(1)}%`;
    }
    if (status.scanning) {
      const progress =
        status.total > 0 ? ` ${status.checked}/${status.total}` : "";
      statusText.textContent = `正在更新${progress}`;
    } else {
      statusText.textContent = `${status.count} 个应用可下载`;
    }
    if (lastKnownCount >= 0 && status.count !== lastKnownCount) {
      search();
    }
    lastKnownCount = status.count;
  } catch {
    statusPill.classList.remove("is-scanning");
    statusText.textContent = "等待服务连接";
    storageText.textContent = "读取失败";
    storagePill.classList.remove("is-critical");
  }
}

function formatStorageSize(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return "—";
  const gib = value / 1024 ** 3;
  return `${gib >= 100 ? gib.toFixed(0) : gib.toFixed(1)} GB`;
}

function formatUploadSize(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function setErrorApkMessage(message, type = "") {
  errorApkMessage.textContent = message;
  errorApkMessage.classList.toggle("is-error", type === "error");
  errorApkMessage.classList.toggle("is-success", type === "success");
}

function chooseErrorApkFile(file) {
  if (!file || !file.name.toLowerCase().endsWith(".zip")) {
    selectedErrorApkFile = null;
    errorApkSelected.textContent = "请选择 ZIP 文件";
    errorApkSelected.classList.add("is-error");
    setErrorApkMessage("只接受 .zip 格式的问题包。", "error");
    return;
  }
  selectedErrorApkFile = file;
  errorApkSelected.textContent =
    `${file.name} · ${formatUploadSize(file.size)}`;
  errorApkSelected.classList.remove("is-error");
  setErrorApkMessage("已选择问题包，请填写原因后提交。");
}

function renderErrorApks(payload) {
  const count = payload.count || 0;
  errorApkTotalCount.textContent = count;
  errorApkNavCount.textContent = count;
  errorApkNavCount.hidden = count === 0;
  errorApkList.replaceChildren();

  if (!payload.items?.length) {
    errorApkList.append(
      createElement("p", "queue-placeholder", "目前没有提交的问题包"),
    );
    return;
  }

  const fragment = document.createDocumentFragment();
  payload.items.forEach((item) => {
    const card = createElement("article", "error-apk-item");
    const main = createElement("div", "error-apk-item-main");
    const titleRow = createElement("div", "error-apk-item-title");
    const title = createElement("strong", "", item.original_name);
    title.title = item.original_name;
    const badge = createElement("span", "", item.size_label);
    titleRow.append(title, badge);
    const submitted = createElement(
      "small",
      "",
      `#${item.id} · ${formatQueueTime(item.created_at)}`,
    );
    const reason = createElement("p", "error-apk-item-reason", item.reason);
    main.append(titleRow, submitted, reason);
    const download = createElement("a", "secondary-button", "下载问题包");
    download.href = item.download_url;
    download.setAttribute("download", item.original_name);
    card.append(main, download);
    fragment.append(card);
  });
  errorApkList.append(fragment);
}

async function loadErrorApks() {
  if (errorApkRequestActive) return;
  errorApkRequestActive = true;
  try {
    const response = await fetch("/api/error-apks", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderErrorApks(await response.json());
  } catch {
    errorApkList.replaceChildren(
      createElement("p", "queue-placeholder is-error", "问题包列表暂时无法连接"),
    );
  } finally {
    errorApkRequestActive = false;
  }
}

async function submitErrorApk(event) {
  event.preventDefault();
  const reason = errorApkReason.value.trim();
  if (!selectedErrorApkFile) {
    setErrorApkMessage("请先拖入或选择问题 ZIP。", "error");
    errorApkDropzone.focus();
    return;
  }
  if (!reason) {
    setErrorApkMessage("请填写问题原因。", "error");
    errorApkReason.focus();
    return;
  }

  errorApkSubmit.disabled = true;
  errorApkFileInput.disabled = true;
  errorApkReason.disabled = true;
  errorApkSubmit.textContent = "正在上传…";
  setErrorApkMessage(
    `正在上传 ${selectedErrorApkFile.name}，大文件请稍候…`,
  );
  try {
    const parameters = new URLSearchParams({
      filename: selectedErrorApkFile.name,
      reason,
    });
    const response = await fetch(`/api/error-apks?${parameters}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/zip",
      },
      body: selectedErrorApkFile,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    setErrorApkMessage("问题包已提交到这台电脑。", "success");
    selectedErrorApkFile = null;
    errorApkFileInput.value = "";
    errorApkReason.value = "";
    errorApkSelected.textContent = "尚未选择文件";
    await loadErrorApks();
  } catch (error) {
    setErrorApkMessage(`提交失败：${error.message}`, "error");
  } finally {
    errorApkSubmit.disabled = false;
    errorApkFileInput.disabled = false;
    errorApkReason.disabled = false;
    errorApkSubmit.textContent = "提交问题包";
  }
}

const queueStatusLabels = {
  pending: "待处理",
  processing: "正在寻找",
  completed: "已完成",
  retry: "等待重试",
  paid_skipped: "付费已跳过",
  not_found_skipped: "无结果已跳过",
  manual_ios: "iOS 应用",
  manual_paid: "付费应用",
  manual_not_found: "找不到",
};

function formatQueueTime(timestamp) {
  if (!timestamp) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "2-digit",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp * 1000));
}

function setCodexMessage(message, type = "") {
  codexMessage.textContent = message;
  codexMessage.classList.toggle("is-error", type === "error");
  codexMessage.classList.toggle("is-success", type === "success");
}

function renderCodexController(snapshot, { syncSettings = false } = {}) {
  const settings = snapshot.settings || {};
  const workers = snapshot.workers || [];
  const running = workers.filter((worker) => worker.status === "running" || worker.status === "starting");
  if (syncSettings || !codexSettingsLoaded || !codexSettingsDirty) {
    codexEnabled.checked = Boolean(settings.enabled);
    codexModel.value = settings.model || "gpt-5.6-luna";
    if (!codexModel.value) codexModel.value = "gpt-5.6-luna";
    codexEffort.value = settings.effort || "max";
    codexInterval.value = settings.interval_minutes || 30;
    codexBatchSize.value = settings.batch_size || 5;
    codexWorkerCount.value = settings.workers || 4;
    codexSettingsLoaded = true;
    if (syncSettings) codexSettingsDirty = false;
  }
  codexEnabledState.textContent = settings.enabled ? "已开启" : "已关闭";
  codexNextRun.textContent = settings.enabled
    ? (snapshot.next_run_at ? `下次 ${formatQueueTime(snapshot.next_run_at)}` : "等待下一次运行")
    : "仅手动开始";
  codexRunningCount.textContent = running.length;
  const batchRemaining = snapshot.batch_remaining ?? settings.batch_size ?? 5;
  codexBatchSummary.textContent = `${batchRemaining} 个`;
  codexServerState.querySelector("span:last-child").textContent = !snapshot.available
    ? "本机未找到 Codex"
    : snapshot.server_running
      ? "Codex 已连接"
      : "Codex 按需启动";
  codexServerState.classList.toggle("is-error", !snapshot.available || Boolean(snapshot.last_error));
  codexStopButton.disabled = running.length === 0 || codexRequestActive;
  codexRunButton.disabled = !snapshot.available || codexRequestActive;
  codexSaveButton.disabled = codexRequestActive;
  const previousStreamPositions = new Map();
  codexWorkers.querySelectorAll(".codex-worker[data-worker-id]").forEach((workerItem) => {
    const stream = workerItem.querySelector(".codex-stream");
    if (!stream) return;
    previousStreamPositions.set(workerItem.dataset.workerId, {
      scrollTop: stream.scrollTop,
      atBottom: stream.scrollTop + stream.clientHeight >= stream.scrollHeight - 6,
    });
  });
  codexWorkers.replaceChildren();
  workers.forEach((worker) => {
    const item = createElement("article", `codex-worker is-${worker.status}`);
    item.dataset.workerId = worker.worker_id;
    const copy = createElement("div", "codex-worker-copy");
    copy.append(
      createElement("strong", "", worker.worker_id.replace("lan-codex-", "Agent ")),
      createElement("span", "", worker.detail || "等待启动"),
    );
    const meta = createElement("div", "codex-worker-meta");
    const status = { idle: "空闲", starting: "启动中", running: "运行中", error: "异常" }[worker.status] || worker.status;
    meta.append(
      createElement("b", "", status),
      createElement("small", "", worker.started_at ? `开始 ${formatQueueTime(worker.started_at)}` : "尚未运行"),
    );
    const head = createElement("div", "codex-worker-head");
    head.append(copy, meta);
    const stream = createElement("div", "codex-stream");
    const entries = Array.isArray(worker.stream) && worker.stream.length
      ? worker.stream
      : [worker.detail || "等待启动"];
    entries.slice(-12).forEach((entry) => {
      stream.append(createElement("p", "", entry));
    });
    item.append(head, stream);
    codexWorkers.append(item);
    const previousPosition = previousStreamPositions.get(worker.worker_id);
    requestAnimationFrame(() => {
      stream.scrollTop = previousPosition?.atBottom
        ? stream.scrollHeight
        : (previousPosition?.scrollTop || 0);
    });
  });
  if (snapshot.last_error && !running.length) {
    setCodexMessage(snapshot.last_error, "error");
  }
}

async function loadCodexController() {
  if (!codexPanel.classList.contains("is-active") || codexRequestActive) return;
  try {
    const response = await fetch("/api/codex-controller", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderCodexController(await response.json());
  } catch (error) {
    setCodexMessage(`无法读取 Codex 状态：${error.message}`, "error");
  }
}

function renderBrowserWorker(snapshot) {
  const worker = snapshot.worker || {};
  const counts = snapshot.counts || {};
  const labels = {
    idle: "已就绪",
    running: "运行中",
    unavailable: "不可用",
    stopped: "已停止",
  };
  browserWorkerState.textContent = labels[worker.status] || worker.status || "未知";
  const waiting = Number(counts.pending || 0);
  const current = worker.current_task_id ? `任务 #${worker.current_task_id}` : "";
  browserWorkerDetail.textContent = [
    worker.detail || "等待浏览器状态",
    current,
    waiting ? `排队 ${waiting}` : "",
  ].filter(Boolean).join(" · ");
}

async function loadBrowserWorker() {
  if (!codexPanel.classList.contains("is-active")) return;
  try {
    let response = await fetch("/api/browser-worker", { cache: "no-store" });
    if (response.status === 404) {
      response = await fetch("/static/browser-worker-status.json", {
        cache: "no-store",
      });
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderBrowserWorker(await response.json());
  } catch (error) {
    browserWorkerState.textContent = "读取失败";
    browserWorkerDetail.textContent = error.message;
  }
}

function codexSettingsPayload() {
  return {
    enabled: codexEnabled.checked,
    model: codexModel.value,
    effort: codexEffort.value,
    interval_minutes: Number(codexInterval.value),
    batch_size: Number(codexBatchSize.value),
    workers: Number(codexWorkerCount.value),
  };
}

async function saveCodexSettings(event) {
  event.preventDefault();
  codexRequestActive = true;
  setCodexMessage("正在保存设置…");
  try {
    const response = await fetch("/api/codex-controller/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(codexSettingsPayload()),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    renderCodexController(payload, { syncSettings: true });
    setCodexMessage(payload.settings.enabled ? "定时领取已开启。" : "设置已保存，当前仅手动开始。", "success");
  } catch (error) {
    setCodexMessage(`保存失败：${error.message}`, "error");
  } finally {
    codexRequestActive = false;
    await loadCodexController();
  }
}

async function runCodexNow() {
  if (codexRequestActive) return;
  codexRequestActive = true;
  setCodexMessage("正在保存设置并启动本机 Codex…");
  try {
    const settingsResponse = await fetch("/api/codex-controller/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(codexSettingsPayload()),
    });
    const settingsPayload = await settingsResponse.json().catch(() => ({}));
    if (!settingsResponse.ok) {
      throw new Error(settingsPayload.detail || `HTTP ${settingsResponse.status}`);
    }
    const response = await fetch("/api/codex-controller/run", { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    renderCodexController(payload, { syncSettings: true });
    setCodexMessage(payload.started ? `已启动 ${payload.started} 个 Agent。` : "没有空闲 Agent 可启动。", "success");
  } catch (error) {
    setCodexMessage(`启动失败：${error.message}`, "error");
  } finally {
    codexRequestActive = false;
    await loadCodexController();
  }
}

async function stopCodexNow() {
  if (codexRequestActive) return;
  if (!window.confirm("停止当前批次？已领取但未完成的关键词会保留在队列中。")) return;
  codexRequestActive = true;
  setCodexMessage("正在停止当前批次…");
  try {
    const response = await fetch("/api/codex-controller/stop", { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    renderCodexController(payload);
    setCodexMessage("已发送停止请求。", "success");
  } catch (error) {
    setCodexMessage(`停止失败：${error.message}`, "error");
  } finally {
    codexRequestActive = false;
    await loadCodexController();
  }
}

function formatDuration(job) {
  if (!job.claimed_at) return "—";
  const ending =
    job.completed_at ||
    (job.status === "processing" ? Date.now() / 1000 : job.updated_at);
  const seconds = Math.max(0, Math.round(ending - job.claimed_at));
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours} 小时 ${minutes} 分`;
}

function queueResult(job) {
  if (job.status === "completed") {
    return job.delivery_directory ? "已入库" : "已完成";
  }
  if (job.status === "paid_skipped") return "付费应用已跳过";
  if (job.status === "not_found_skipped") {
    return job.last_error || "一次完整有效搜索无结果，已跳过";
  }
  if (job.status === "manual_ios") {
    return job.last_error || "人工确认只有 iOS 版本";
  }
  if (job.status === "manual_paid") {
    return job.last_error || "人工确认是付费应用";
  }
  if (job.status === "manual_not_found") {
    return job.last_error || "人工确认找不到 APK";
  }
  if (job.status === "retry") return job.last_error || "等待下次重试";
  if (job.status === "processing") return "正在查找安装包";
  return "等待定时任务领取";
}

function setQueueMessage(message, tone = "") {
  queueMessage.textContent = message;
  queueMessage.classList.toggle("is-success", tone === "success");
  queueMessage.classList.toggle("is-error", tone === "error");
}

function createQueueItem(job) {
  const row = createElement("tr", "queue-row");
  const id = createElement("td", "queue-id", `#${job.id}`);
  const keywordCell = createElement("td", "queue-keyword");
  const keyword = createElement("strong", "", job.keyword);
  keyword.title = job.keyword;
  keywordCell.append(keyword);
  if (job.last_error) {
    const error = createElement("span", "queue-item-error", job.last_error);
    error.title = job.last_error;
    keywordCell.append(error);
  }

  const statusCell = createElement("td", "queue-status-cell");
  const status = createElement(
    "span",
    `queue-status status-${job.status}`,
    queueStatusLabels[job.status] || job.status,
  );
  statusCell.append(status);

  const submitted = createElement(
    "td",
    "queue-time",
    formatQueueTime(job.created_at),
  );
  const started = createElement(
    "td",
    "queue-time",
    formatQueueTime(job.claimed_at),
  );
  const duration = createElement("td", "queue-duration", formatDuration(job));
  const attempts = createElement(
    "td",
    "queue-attempts",
    String(job.attempt_count || 0),
  );
  const result = createElement("td", "queue-result", queueResult(job));
  result.title = job.delivery_directory || job.last_error || result.textContent;

  row.append(
    id,
    keywordCell,
    statusCell,
    submitted,
    started,
    duration,
    attempts,
    result,
  );
  return row;
}

function renderQueue(snapshot) {
  latestQueueSnapshot = snapshot;
  const counts = snapshot.counts || {};
  queueWaitingCount.textContent = (counts.pending || 0) + (counts.retry || 0);
  queueProcessingCount.textContent = counts.processing || 0;
  queueCompletedCount.textContent =
    (counts.completed || 0) +
    (counts.paid_skipped || 0) +
    (counts.not_found_skipped || 0) +
    (counts.manual_ios || 0) +
    (counts.manual_paid || 0) +
    (counts.manual_not_found || 0);
  const activeCount =
    (counts.pending || 0) +
    (counts.retry || 0) +
    (counts.processing || 0);
  queueNavCount.textContent = activeCount;
  queueNavCount.hidden = activeCount === 0;
  const skippedCount =
    (counts.not_found_skipped || 0) +
    (counts.paid_skipped || 0);
  notFoundNavCount.textContent = skippedCount;
  notFoundNavCount.hidden = skippedCount === 0;
  notFoundMissingCount.textContent = skippedCount;
  notFoundIosCount.textContent = counts.manual_ios || 0;
  notFoundManualCount.textContent = counts.manual_not_found || 0;
  notFoundPaidCount.textContent = counts.manual_paid || 0;

  queueList.replaceChildren();
  if (!snapshot.items?.length) {
    const row = createElement("tr");
    const empty = createElement("td", "queue-placeholder", "还没有提交关键词");
    empty.colSpan = 8;
    row.append(empty);
    queueList.append(row);
  } else {
    const fragment = document.createDocumentFragment();
    snapshot.items.forEach((job) => fragment.append(createQueueItem(job)));
    queueList.append(fragment);
  }

  const pagination = snapshot.pagination || {};
  const currentPage = pagination.page || 1;
  const totalPages = pagination.total_pages || 1;
  const total = pagination.total || 0;
  queuePageSummary.textContent = `第 ${currentPage} / ${totalPages} 页 · 共 ${total} 条`;
  queuePagePrev.disabled = currentPage <= 1;
  queuePageNext.disabled = currentPage >= totalPages;
}

function createNotFoundItem(job) {
  const row = createElement("tr", "queue-row");
  const id = createElement("td", "queue-id", `#${job.id}`);
  const keywordCell = createElement("td", "queue-keyword");
  const keyword = createElement("strong", "", job.keyword);
  keyword.title = job.keyword;
  keywordCell.append(keyword);
  const statusCell = createElement("td", "queue-status-cell");
  const status = createElement(
    "span",
    `queue-status status-${job.status}`,
    queueStatusLabels[job.status] || job.status,
  );
  statusCell.append(status);
  const completed = createElement(
    "td",
    "queue-time",
    formatQueueTime(job.completed_at || job.updated_at),
  );
  const rounds = createElement(
    "td",
    "queue-attempts",
    String(job.search_miss_count || 0),
  );
  const attempts = createElement(
    "td",
    "queue-attempts",
    String(job.attempt_count || 0),
  );
  const defaultReason =
    job.last_error ||
    (job.status === "paid_skipped"
      ? "官方页面确认为付费应用，按规则跳过"
      : job.status === "manual_ios"
        ? "人工确认只有 iOS 版本"
        : job.status === "manual_paid"
          ? "人工确认是付费应用"
          : "完成有效搜索后仍无可下载 Android 安装包");
  const reason = createElement("td", "queue-result notfound-reason");
  const action = createElement("td", "notfound-action");
  if (
    job.status === "paid_skipped" ||
    job.status === "not_found_skipped" ||
    job.status === "manual_ios" ||
    job.status === "manual_paid" ||
    job.status === "manual_not_found"
  ) {
    addNotFoundReasonControls(job, reason, action, defaultReason);
  } else {
    reason.textContent = defaultReason;
    reason.title = defaultReason;
    action.textContent = "—";
  }
  if (job.status === "paid_skipped") rounds.textContent = "—";
  row.append(
    id,
    keywordCell,
    statusCell,
    completed,
    rounds,
    attempts,
    reason,
    action,
  );
  return row;
}

function addNotFoundReasonControls(
  job,
  reasonCell,
  actionCell,
  initialReason,
) {
  let currentReason = initialReason;

  const showReason = ({ endEditing = false } = {}) => {
    if (endEditing && notFoundEditingJobId === job.id) {
      notFoundEditingJobId = null;
    }
    const reasonText = createElement(
      "span",
      "notfound-reason-text",
      currentReason,
    );
    reasonText.title = currentReason;
    reasonCell.replaceChildren(reasonText);

    const editButton = createElement(
      "button",
      "notfound-edit-button",
      "编辑",
    );
    editButton.type = "button";
    editButton.addEventListener("click", showEditor);
    actionCell.replaceChildren(editButton);

    const reopenButton = createElement(
      "button",
      "notfound-reopen-button",
      "重新查找",
    );
    reopenButton.type = "button";
    reopenButton.addEventListener("click", () =>
      reopenKeyword(job, reopenButton),
    );

    const categories = [
      { value: "ios", status: "manual_ios", label: "iOS" },
      { value: "paid", status: "manual_paid", label: "付费" },
      { value: "not_found", status: "manual_not_found", label: "找不到" },
    ];
    categories.forEach((category) => {
      const confirmButton = createElement(
        "button",
        `notfound-confirm-button category-${category.value}`,
        job.status === category.status
          ? `${category.label} ✓`
          : category.label,
      );
      confirmButton.type = "button";
      confirmButton.disabled = job.status === category.status;
      confirmButton.classList.toggle(
        "is-current",
        job.status === category.status,
      );
      confirmButton.addEventListener("click", () =>
        confirmManualNotFound(
          job,
          currentReason,
          confirmButton,
          category.value,
        ),
      );
      actionCell.append(confirmButton);
    });
    actionCell.append(reopenButton);
  };

  const showEditor = () => {
    notFoundEditingJobId = job.id;
    const reasonInput = createElement("textarea", "notfound-reason-input");
    reasonInput.value = currentReason;
    reasonInput.rows = 2;
    reasonInput.maxLength = 500;
    reasonInput.setAttribute("aria-label", `${job.keyword} 的最终原因`);
    reasonInput.addEventListener("input", () =>
      reasonInput.setCustomValidity(""),
    );
    reasonCell.replaceChildren(reasonInput);

    const saveButton = createElement(
      "button",
      "notfound-edit-button is-save",
      "保存",
    );
    saveButton.type = "button";
    const cancelButton = createElement(
      "button",
      "notfound-cancel-button",
      "取消",
    );
    cancelButton.type = "button";
    cancelButton.addEventListener("click", () =>
      showReason({ endEditing: true }),
    );
    saveButton.addEventListener("click", async () => {
      const editedReason = reasonInput.value.trim();
      if (!editedReason) {
        reasonInput.setCustomValidity("请填写最终原因");
        reasonInput.reportValidity();
        return;
      }
      reasonInput.disabled = true;
      saveButton.disabled = true;
      cancelButton.disabled = true;
      saveButton.textContent = "保存中…";
      const saved = await updateSkippedReason(job, editedReason);
      if (saved) {
        currentReason = editedReason;
        showReason({ endEditing: true });
        return;
      }
      reasonInput.disabled = false;
      saveButton.disabled = false;
      cancelButton.disabled = false;
      saveButton.textContent = "保存";
      reasonInput.setCustomValidity("保存失败，请确认服务仍在运行");
      reasonInput.reportValidity();
    });
    actionCell.replaceChildren(saveButton, cancelButton);
    reasonInput.focus();
  };

  showReason();
}

async function updateSkippedReason(job, reason) {
  try {
    const response = await fetch(
      `/api/keywords/${job.id}/skipped-reason`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ reason }),
      },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    job.last_error = reason;
    return true;
  } catch {
    return false;
  }
}

async function confirmManualNotFound(job, reason, button, category) {
  button.disabled = true;
  const originalLabel = button.textContent;
  button.textContent = "确认中…";
  try {
    const response = await fetch(
      `/api/keywords/${job.id}/manual-not-found`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ reason, category }),
      },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    button.textContent = "已确认";
    await Promise.all([loadQueue(), loadNotFound()]);
  } catch {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

async function reopenKeyword(job, button) {
  button.disabled = true;
  const originalLabel = button.textContent;
  button.textContent = "退回中…";
  try {
    const response = await fetch(`/api/keywords/${job.id}/reopen`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        reason: "人工复核后退回重新查找",
        candidate_url: "",
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    button.textContent = "已退回";
    notFoundEditingJobId = null;
    await Promise.all([loadQueue(), loadNotFound()]);
  } catch {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

function renderNotFound(snapshot) {
  latestNotFoundSnapshot = snapshot;
  const missingCount = snapshot.counts?.not_found_skipped || 0;
  const skippedPaidCount = snapshot.counts?.paid_skipped || 0;
  const iosCount = snapshot.counts?.manual_ios || 0;
  const manualPaidCount = snapshot.counts?.manual_paid || 0;
  const manualCount = snapshot.counts?.manual_not_found || 0;
  const navCount = missingCount + skippedPaidCount;
  notFoundMissingCount.textContent = navCount;
  notFoundIosCount.textContent = iosCount;
  notFoundManualCount.textContent = manualCount;
  notFoundPaidCount.textContent = manualPaidCount;
  notFoundNavCount.textContent = navCount;
  notFoundNavCount.hidden = navCount === 0;

  notFoundList.replaceChildren();
  if (!snapshot.items?.length) {
    const row = createElement("tr");
    const empty = createElement(
      "td",
      "queue-placeholder",
      notFoundQuery
        ? "没有匹配的记录"
        : notFoundMode === "ios"
          ? "目前没有人工确认的 iOS 应用"
          : notFoundMode === "paid"
            ? "目前没有人工确认的付费应用"
            : notFoundMode === "not_found"
              ? "目前没有人工确认找不到的记录"
              : "目前没有待人工确认的记录",
    );
    empty.colSpan = 8;
    row.append(empty);
    notFoundList.append(row);
  } else {
    const fragment = document.createDocumentFragment();
    snapshot.items.forEach((job) =>
      fragment.append(createNotFoundItem(job)),
    );
    notFoundList.append(fragment);
  }

  const pagination = snapshot.pagination || {};
  const currentPage = pagination.page || 1;
  const totalPages = pagination.total_pages || 1;
  const total = pagination.total || 0;
  notFoundPageSummary.textContent =
    `第 ${currentPage} / ${totalPages} 页 · 共 ${total} 条`;
  notFoundPagePrev.disabled = currentPage <= 1;
  notFoundPageNext.disabled = currentPage >= totalPages;
}

async function loadNotFound() {
  if (notFoundRequestActive || notFoundEditingJobId !== null) return;
  notFoundRequestActive = true;
  try {
    const query = encodeURIComponent(notFoundQuery);
    const statuses = {
      pending: "skipped",
      ios: "manual_ios",
      paid: "manual_paid",
      not_found: "manual_not_found",
    };
    const status = statuses[notFoundMode];
    const response = await fetch(
      `/api/keywords?status=${status}&q=${query}&page=${notFoundPage}&page_size=${notFoundPageSize}`,
      {
        headers: { Accept: "application/json" },
        cache: "no-store",
      },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const snapshot = await response.json();
    if (notFoundEditingJobId === null) renderNotFound(snapshot);
  } catch {
    notFoundList.replaceChildren();
    const row = createElement("tr");
    const error = createElement(
      "td",
      "queue-placeholder is-error",
      "跳过记录暂时无法连接",
    );
    error.colSpan = 8;
    row.append(error);
    notFoundList.append(row);
  } finally {
    notFoundRequestActive = false;
  }
}

function cloudflareDisplayName(keyword) {
  return String(keyword || "").replace(/^\s*\d+\.\s*/, "").trim() || "APK";
}

function cloudflareReason(reason) {
  const value = String(reason || "等待浏览器验证").trim();
  const prefix = "精确候选仍存在，当前仅因验证或临时下载失败等待重试：";
  return value.startsWith(prefix) ? value.slice(prefix.length) : value;
}

function createCloudflareIcon(job) {
  const name = cloudflareDisplayName(job.keyword);
  const fallback = () => {
    const initial = createElement(
      "span",
      "cloudflare-app-icon cloudflare-icon-fallback",
      name.slice(0, 1).toLocaleUpperCase(),
    );
    initial.setAttribute("aria-hidden", "true");
    return initial;
  };
  if (!job.icon_url) return fallback();
  const icon = createElement("img", "cloudflare-app-icon");
  icon.src = job.icon_url;
  icon.alt = `${name} 图标`;
  icon.loading = "lazy";
  icon.width = 64;
  icon.height = 64;
  icon.addEventListener("error", () => icon.replaceWith(fallback()), {
    once: true,
  });
  return icon;
}

function createCloudflareCard(job) {
  const card = createElement("article", "cloudflare-card");
  const icon = createCloudflareIcon(job);
  const content = createElement("div", "cloudflare-card-content");
  const heading = createElement("div", "cloudflare-card-heading");
  const titleGroup = createElement("div");
  const title = createElement("h3", "", cloudflareDisplayName(job.keyword));
  title.title = job.keyword || "";
  const packageName = createElement(
    "span",
    "cloudflare-package",
    job.package_name || job.candidate_host || "精确候选页",
  );
  titleGroup.append(title, packageName);
  const badge = createElement("span", "cloudflare-badge", "Cloudflare 拦截");
  heading.append(titleGroup, badge);

  const reason = createElement(
    "p",
    "cloudflare-reason",
    cloudflareReason(job.last_error),
  );
  reason.title = cloudflareReason(job.last_error);

  const footer = createElement("div", "cloudflare-card-footer");
  const meta = createElement(
    "span",
    "cloudflare-meta",
    `更新 ${formatQueueTime(job.updated_at)} · 已尝试 ${job.attempt_count || 0} 次`,
  );
  const link = createElement("a", "cloudflare-link", "打开候选页");
  link.href = job.candidate_url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", `打开 ${cloudflareDisplayName(job.keyword)} 候选页`);
  footer.append(meta, link);

  content.append(heading, reason, footer);
  card.append(icon, content);
  return card;
}

function renderCloudflareBlocked(snapshot) {
  latestCloudflareSnapshot = snapshot;
  const pagination = snapshot.pagination || {};
  const total = pagination.total || 0;
  cloudflareTotalCount.textContent = total;
  cloudflareNavCount.textContent = total;
  cloudflareNavCount.hidden = total === 0;
  cloudflareList.replaceChildren();

  if (!snapshot.items?.length) {
    cloudflareList.append(
      createElement(
        "p",
        "cloudflare-placeholder",
        "当前没有等待 Cloudflare 验证的精确候选。",
      ),
    );
  } else {
    const fragment = document.createDocumentFragment();
    snapshot.items.forEach((job) => fragment.append(createCloudflareCard(job)));
    cloudflareList.append(fragment);
  }

  const currentPage = pagination.page || 1;
  const totalPages = pagination.total_pages || 1;
  cloudflarePageSummary.textContent =
    `第 ${currentPage} / ${totalPages} 页 · 共 ${total} 条`;
  cloudflarePagePrev.disabled = currentPage <= 1;
  cloudflarePageNext.disabled = currentPage >= totalPages;
}

async function loadCloudflareBlocked() {
  if (cloudflareRequestActive) return;
  cloudflareRequestActive = true;
  try {
    const response = await fetch(
      `/api/cloudflare-blocked?page=${cloudflarePage}&page_size=${cloudflarePageSize}`,
      { headers: { Accept: "application/json" }, cache: "no-store" },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderCloudflareBlocked(await response.json());
  } catch {
    cloudflareList.replaceChildren(
      createElement(
        "p",
        "cloudflare-placeholder is-error",
        "Cloudflare 拦截记录暂时无法连接",
      ),
    );
  } finally {
    cloudflareRequestActive = false;
  }
}

function changeCloudflarePage(direction) {
  const pagination = latestCloudflareSnapshot?.pagination || {};
  const totalPages = pagination.total_pages || 1;
  const nextPage = Math.min(
    totalPages,
    Math.max(1, cloudflarePage + direction),
  );
  if (nextPage === cloudflarePage) return;
  cloudflarePage = nextPage;
  loadCloudflareBlocked();
}

async function loadQueue() {
  if (queueRequestActive) return;
  queueRequestActive = true;
  try {
    const response = await fetch(
      `/api/keywords?page=${queuePage}&page_size=${queuePageSize}`,
      {
      headers: { Accept: "application/json" },
      cache: "no-store",
      },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderQueue(await response.json());
  } catch {
    queueList.replaceChildren();
    const row = createElement("tr");
    const error = createElement(
      "td",
      "queue-placeholder is-error",
      "关键词队列暂时无法连接",
    );
    error.colSpan = 8;
    row.append(error);
    queueList.append(row);
  } finally {
    queueRequestActive = false;
  }
}

function keywordsFromInput() {
  return keywordInput.value
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
}

async function saveInputKeywords() {
  const keywords = keywordsFromInput();
  if (!keywords.length) {
    setQueueMessage("请至少输入一个应用关键词。", "error");
    keywordInput.focus();
    return false;
  }
  queueAddButton.disabled = true;
  setQueueMessage("正在加入关键词队列…");
  try {
    const response = await fetch("/api/keywords", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ keywords }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const added = payload.created?.length || 0;
    const existing = payload.existing?.length || 0;
    const invalid = payload.invalid?.length || 0;
    const pieces = [`已加入 ${added} 个关键词`];
    if (existing) pieces.push(`${existing} 个已在队列中`);
    if (invalid) pieces.push(`${invalid} 个格式无效`);
    setQueueMessage(`${pieces.join("，")}。`, added ? "success" : "");
    if (added) keywordInput.value = "";
    queuePage = 1;
    await loadQueue();
    return true;
  } catch {
    setQueueMessage("加入失败，请确认服务仍在运行。", "error");
    return false;
  } finally {
    queueAddButton.disabled = false;
  }
}

async function addKeywords(event) {
  event.preventDefault();
  await saveInputKeywords();
}

function changeQueuePage(direction) {
  const pagination = latestQueueSnapshot?.pagination || {};
  const totalPages = pagination.total_pages || 1;
  const nextPage = Math.min(totalPages, Math.max(1, queuePage + direction));
  if (nextPage === queuePage) return;
  queuePage = nextPage;
  loadQueue();
}

function changeNotFoundPage(direction) {
  const pagination = latestNotFoundSnapshot?.pagination || {};
  const totalPages = pagination.total_pages || 1;
  const nextPage = Math.min(
    totalPages,
    Math.max(1, notFoundPage + direction),
  );
  if (nextPage === notFoundPage) return;
  notFoundPage = nextPage;
  loadNotFound();
}

function searchNotFound() {
  notFoundQuery = notFoundSearchInput.value.trim();
  notFoundPage = 1;
  loadNotFound();
}

function changeNotFoundMode(mode) {
  if (
    !["pending", "ios", "paid", "not_found"].includes(mode) ||
    mode === notFoundMode
  ) return;
  notFoundEditingJobId = null;
  notFoundMode = mode;
  notFoundPage = 1;
  notFoundModeButtons.forEach((button) => {
    const active = button.dataset.notfoundMode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  loadNotFound();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(debounceTimer);
  search();
});

input.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => search(), 180);
});

queueForm.addEventListener("submit", addKeywords);
errorApkForm.addEventListener("submit", submitErrorApk);
errorApkDropzone.addEventListener("click", () => errorApkFileInput.click());
errorApkDropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    errorApkFileInput.click();
  }
});
errorApkFileInput.addEventListener("change", () =>
  chooseErrorApkFile(errorApkFileInput.files?.[0]),
);
["dragenter", "dragover"].forEach((eventName) => {
  errorApkDropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    errorApkDropzone.classList.add("is-dragging");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  errorApkDropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    errorApkDropzone.classList.remove("is-dragging");
  });
});
errorApkDropzone.addEventListener("drop", (event) => {
  chooseErrorApkFile(event.dataTransfer?.files?.[0]);
});
queuePagePrev.addEventListener("click", () => changeQueuePage(-1));
queuePageNext.addEventListener("click", () => changeQueuePage(1));
notFoundPagePrev.addEventListener("click", () => changeNotFoundPage(-1));
notFoundPageNext.addEventListener("click", () => changeNotFoundPage(1));
cloudflarePagePrev.addEventListener("click", () => changeCloudflarePage(-1));
cloudflarePageNext.addEventListener("click", () => changeCloudflarePage(1));
notFoundSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(notFoundSearchTimer);
  searchNotFound();
});
notFoundSearchInput.addEventListener("input", () => {
  clearTimeout(notFoundSearchTimer);
  notFoundSearchTimer = setTimeout(searchNotFound, 180);
});
notFoundModeButtons.forEach((button) => {
  button.addEventListener("click", () =>
    changeNotFoundMode(button.dataset.notfoundMode),
  );
});
productionLaneADate.addEventListener("change", () => {
  chooseProductionDate(1, productionLaneADate.value);
});
productionLaneBDate.addEventListener("change", () => {
  chooseProductionDate(2, productionLaneBDate.value);
});
productionDateStepButtons.forEach((button) => {
  button.addEventListener("click", () => {
    shiftProductionDate(
      Number(button.dataset.productionDateStep),
      Number(button.dataset.direction),
    );
  });
});
productionCleanupButton.addEventListener(
  "click",
  cleanupDownloadedProduction,
);
codexSettingsForm.addEventListener("submit", saveCodexSettings);
codexRunButton.addEventListener("click", runCodexNow);
codexStopButton.addEventListener("click", stopCodexNow);
[codexEnabled, codexModel, codexEffort, codexInterval, codexBatchSize, codexWorkerCount].forEach(
  (control) => {
    const markCodexSettingsDirty = () => {
    codexSettingsDirty = true;
    };
    control.addEventListener("change", markCodexSettingsDirty);
    control.addEventListener("input", markCodexSettingsDirty);
  },
);
navTabs.forEach((tab) => {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
});
sidebarToggle.addEventListener("click", () => {
  setSidebarCollapsed(
    !document.body.classList.contains("is-sidebar-collapsed"),
  );
});
viewSwitches.forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.switchView));
});

let initialView = "library";
let initialSidebarCollapsed = false;
try {
  initialView = localStorage.getItem("find-apk-admin-view") || "library";
  initialSidebarCollapsed =
    localStorage.getItem("find-apk-sidebar-collapsed") === "1";
} catch {
  initialView = "library";
  initialSidebarCollapsed = false;
}
setSidebarCollapsed(initialSidebarCollapsed, { remember: false });
switchView(initialView, { remember: false });

search();
updateStatus();
loadQueue();
loadNotFound();
loadCloudflareBlocked();
loadErrorApks();
loadCodexController();
loadBrowserWorker();
setInterval(updateStatus, 3000);
setInterval(loadQueue, 4000);
setInterval(loadNotFound, 4000);
setInterval(loadCloudflareBlocked, 5000);
setInterval(loadProduction, 4000);
setInterval(loadErrorApks, 5000);
setInterval(loadCodexController, 3000);
setInterval(loadBrowserWorker, 3000);
