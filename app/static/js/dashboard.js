(function () {
  var refreshIntervalMs = 180000;
  var retryIntervalMs = 15000;
  var ringCircumference = 263.89378290154264;
  var timerId = null;
  var countdownTimerId = null;
  var toastTimerId = null;
  var syncing = false;

  function applyStandaloneMode() {
    var isStandalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;
    if (isStandalone) {
      document.documentElement.classList.add("standalone");
      document.body.classList.add("standalone");
    }
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function formatRelativeDuration(targetDate) {
    if (!targetDate || Number.isNaN(targetDate.getTime())) {
      return "未知";
    }
    var deltaMs = targetDate.getTime() - Date.now();
    if (deltaMs <= 60000) {
      return "即将重置";
    }
    var totalMinutes = Math.floor(deltaMs / 60000);
    var days = Math.floor(totalMinutes / 1440);
    var hours = Math.floor((totalMinutes % 1440) / 60);
    var minutes = totalMinutes % 60;
    var parts = [];
    if (days > 0) parts.push(days + "d");
    if (hours > 0) parts.push(hours + "h");
    if (minutes > 0 && days === 0) parts.push(minutes + "m");
    return parts.slice(0, 2).join(" ") || "即将重置";
  }

  function formatLastSync(targetDate) {
    if (!targetDate || Number.isNaN(targetDate.getTime())) {
      return "等待首次同步";
    }
    var deltaMs = Date.now() - targetDate.getTime();
    if (deltaMs < 60000) return "最近同步：刚刚";
    var deltaMinutes = Math.floor(deltaMs / 60000);
    if (deltaMinutes < 60) return "最近同步：" + deltaMinutes + " 分钟前";
    return "最近同步：" + targetDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function dashboardApiUrl(forceRefresh) {
    var params = new URLSearchParams(window.location.search);
    var accountId = document.body.getAttribute("data-dashboard-account-id") || params.get("account_id") || "";
    var url = forceRefresh ? "/api/v1/dashboard/refresh" : "/api/v1/dashboard";
    if (accountId) url += "?account_id=" + encodeURIComponent(accountId);
    return url;
  }

  function metricMinutes(metric) {
    if (!metric) return null;
    if (metric.window_minutes !== null && metric.window_minutes !== undefined) return Number(metric.window_minutes);
    if (metric.window_seconds !== null && metric.window_seconds !== undefined) {
      return Math.max(1, Math.floor(Number(metric.window_seconds) / 60));
    }
    return null;
  }

  function normalizeMetric(metric) {
    if (!metric) return null;
    var metricType = String(metric.metric_type || "").toLowerCase();
    var label = String(metric.label || "").toLowerCase();
    var minutes = metricMinutes(metric);
    var normalizedType = null;
    if (metricType === "session" || minutes === 300 || label.indexOf("5h") !== -1 || label.indexOf("5 h") !== -1) {
      normalizedType = "session";
    } else if (
      metricType === "weekly" ||
      minutes === 10080 ||
      label.indexOf("weekly") !== -1 ||
      label.indexOf("week") !== -1 ||
      label.indexOf("周") !== -1
    ) {
      normalizedType = "weekly";
    }
    if (!normalizedType) return null;
    return Object.assign({}, metric, {
      metric_type: normalizedType,
      label: normalizedType === "session" ? "5h 额度" : "周额度"
    });
  }

  function remainingValue(metric) {
    if (!metric || metric.remaining_pct === null || metric.remaining_pct === undefined) return null;
    var remaining = Number(metric.remaining_pct);
    if (Number.isNaN(remaining)) return null;
    return Math.max(0, Math.min(100, remaining));
  }

  function getTierClass(remaining) {
    if (remaining === null || remaining === undefined || Number.isNaN(remaining)) return "tier-unknown";
    if (remaining > 75) return "tier-75-plus";
    if (remaining > 50) return "tier-50-75";
    if (remaining > 25) return "tier-25-50";
    return "tier-25-below";
  }

  function sourceLabel(sourceType) {
    var labels = {
      oauth: "OAuth",
      cli_rpc: "CLI RPC",
      web_session: "Web Session",
      dom_fallback: "Web 页面兼容",
      local_snapshot: "本地测试数据"
    };
    return labels[sourceType] || "等待同步";
  }

  function showToast(message, danger) {
    var toast = document.querySelector("[data-toast]");
    if (!toast) return;
    window.clearTimeout(toastTimerId);
    toast.textContent = message;
    toast.className = "toast show" + (danger ? " danger" : "");
    toastTimerId = window.setTimeout(function () { toast.className = "toast"; }, 2400);
  }

  function setSyncing(next) {
    syncing = next;
    var button = document.querySelector("[data-refresh-link]");
    var label = document.querySelector("[data-refresh-label]");
    if (button) button.disabled = next;
    if (label) label.textContent = next ? "同步中…" : "同步额度";
  }

  function setMessageBanner(message) {
    var main = document.querySelector(".main");
    var banner = document.querySelector("[data-message-banner]");
    if (!message) {
      if (banner) banner.remove();
      return;
    }
    if (!banner && main) {
      banner = document.createElement("div");
      banner.className = "message-banner";
      banner.setAttribute("data-message-banner", "true");
      main.insertBefore(banner, main.firstChild);
    }
    if (banner) banner.textContent = message;
  }

  function removeEmptyState() {
    var empty = document.querySelector("[data-empty-state]");
    if (empty) empty.remove();
  }

  function ensureEmptyState() {
    var empty = document.querySelector("[data-empty-state]");
    var main = document.querySelector(".main");
    if (empty || !main) return;
    empty = document.createElement("div");
    empty.className = "empty-state";
    empty.setAttribute("data-empty-state", "true");
    empty.innerHTML = "<strong>等待额度数据</strong><span>完成账号登录后，Token BI 将展示官方返回的额度窗口。</span>";
    main.appendChild(empty);
  }

  function ensureMetricList() {
    var list = document.querySelector("[data-metric-list]");
    if (list) return list;
    var main = document.querySelector(".main");
    if (!main) return null;
    removeEmptyState();
    list = document.createElement("section");
    list.className = "quota-grid";
    list.setAttribute("data-metric-list", "true");
    main.appendChild(list);
    return list;
  }

  function createMetricCard(metric) {
    var list = ensureMetricList();
    if (!list || !metric || !metric.metric_type) return null;
    var card = document.createElement("article");
    card.className = "quota-card metric-card metric-" + metric.metric_type + " tier-unknown";
    card.setAttribute("data-metric-card", metric.metric_type);
    card.innerHTML =
      '<div class="quota-head"><h2 data-metric-title></h2></div>' +
      '<div class="quota-body">' +
        '<div class="metric-radial" data-metric-radial role="progressbar" aria-valuemin="0" aria-valuemax="100">' +
          '<svg class="metric-radial-svg" viewBox="0 0 100 100" aria-hidden="true" focusable="false">' +
            '<circle class="metric-ring-track" cx="50" cy="50" r="42"></circle>' +
            '<circle class="metric-ring-value" data-metric-ring-value cx="50" cy="50" r="42" stroke-dasharray="' + ringCircumference + '" stroke-dashoffset="' + ringCircumference + '"></circle>' +
          "</svg>" +
          '<div class="metric-radial-inner"><strong class="num" data-metric-percent>--</strong><span>剩余额度</span></div>' +
        "</div>" +
      "</div>" +
      '<div class="reset-row"><span>重置剩余</span><strong class="reset-time num" data-reset-copy>未知</strong></div>';
    list.appendChild(card);
    return card;
  }

  function syncMetricCards(metrics) {
    var safeMetrics = Array.isArray(metrics) ? metrics.map(normalizeMetric).filter(Boolean) : [];
    var wanted = {};
    safeMetrics.forEach(function (metric) {
      wanted[metric.metric_type] = true;
      if (!document.querySelector('[data-metric-card="' + metric.metric_type + '"]')) createMetricCard(metric);
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-metric-card]"), function (card) {
      if (!wanted[card.getAttribute("data-metric-card")]) card.remove();
    });
    var list = document.querySelector("[data-metric-list]");
    if (list) {
      if (!safeMetrics.length) {
        list.remove();
        ensureEmptyState();
      } else {
        list.className = "quota-grid" + (safeMetrics.length === 1 ? " single" : "");
        removeEmptyState();
      }
    } else if (!safeMetrics.length) {
      ensureEmptyState();
    }
    return safeMetrics;
  }

  function updateMetric(metricType, metric) {
    var normalized = normalizeMetric(metric);
    if (!normalized) return;
    var card = document.querySelector('[data-metric-card="' + metricType + '"]') || createMetricCard(normalized);
    if (!card) return;
    var titleNode = card.querySelector("[data-metric-title]");
    var radialNode = card.querySelector("[data-metric-radial]");
    var ringNode = card.querySelector("[data-metric-ring-value]");
    var percentNode = card.querySelector("[data-metric-percent]");
    var resetNode = card.querySelector("[data-reset-copy]");
    var remaining = remainingValue(normalized);
    var safeRemaining = remaining === null ? 0 : remaining;
    var ringOffset = ringCircumference * (100 - safeRemaining) / 100;

    card.className = "quota-card metric-card metric-" + normalized.metric_type + " " + getTierClass(remaining);
    card.setAttribute("data-metric-card", normalized.metric_type);
    if (titleNode) titleNode.textContent = normalized.label;
    if (radialNode) {
      radialNode.setAttribute("aria-label", normalized.label + "剩余 " + (remaining === null ? "未知" : remaining + "%"));
      if (remaining === null) radialNode.removeAttribute("aria-valuenow");
      else radialNode.setAttribute("aria-valuenow", String(remaining));
    }
    if (ringNode) {
      ringNode.setAttribute("stroke-dasharray", String(ringCircumference));
      ringNode.setAttribute("stroke-dashoffset", String(ringOffset));
    }
    if (percentNode) percentNode.textContent = remaining === null ? "--" : remaining + "%";
    if (resetNode) {
      if (normalized.reset_at) {
        resetNode.setAttribute("data-reset-at", normalized.reset_at);
        resetNode.textContent = formatRelativeDuration(new Date(normalized.reset_at));
      } else {
        resetNode.removeAttribute("data-reset-at");
        resetNode.textContent = "未知";
      }
    }
  }

  function updateDashboard(payload) {
    if (!payload) return;
    if (payload.account && payload.account.account_id) {
      document.body.setAttribute("data-dashboard-account-id", payload.account.account_id);
    }
    var accountName = document.querySelector("[data-account-name]");
    if (accountName) accountName.textContent = payload.account && payload.account.masked_email ? payload.account.masked_email : "未登录";
    var sourceLabelNode = document.querySelector("[data-source-label]");
    if (sourceLabelNode) sourceLabelNode.textContent = sourceLabel(payload.summary && payload.summary.source_type);
    var sourceDetailNode = document.querySelector("[data-source-detail]");
    if (sourceDetailNode) {
      sourceDetailNode.textContent = payload.summary && payload.summary.source_detail && payload.summary.source_detail !== "unknown"
        ? payload.summary.source_detail
        : (payload.summary && payload.summary.updated_at ? "已连接" : "待检查");
    }
    var sourceDot = document.querySelector("[data-source-dot]");
    if (sourceDot) sourceDot.className = "health-dot state-" + (payload.state || "empty");
    var lastSync = document.querySelector("[data-last-sync]");
    if (lastSync) {
      if (payload.summary && payload.summary.updated_at) {
        lastSync.setAttribute("data-updated-at", payload.summary.updated_at);
        lastSync.textContent = formatLastSync(new Date(payload.summary.updated_at));
      } else {
        lastSync.removeAttribute("data-updated-at");
        lastSync.textContent = "等待首次同步";
      }
    }
    setMessageBanner(payload.message || "");
    var normalizedMetrics = syncMetricCards(payload.metrics || []);
    normalizedMetrics.forEach(function (metric) { updateMetric(metric.metric_type, metric); });
  }

  function startCountdown(deadlineMs, prefix) {
    var countdownNode = document.querySelector("[data-refresh-countdown]");
    if (!countdownNode) return;
    function renderCountdown() {
      var remainingMs = Math.max(deadlineMs - Date.now(), 0);
      var totalSeconds = Math.ceil(remainingMs / 1000);
      countdownNode.textContent = (prefix || "") + pad(Math.floor(totalSeconds / 60)) + ":" + pad(totalSeconds % 60);
    }
    if (countdownTimerId) window.clearInterval(countdownTimerId);
    renderCountdown();
    countdownTimerId = window.setInterval(renderCountdown, 1000);
  }

  function scheduleRefresh(delayMs, prefix) {
    if (timerId) window.clearTimeout(timerId);
    startCountdown(Date.now() + delayMs, prefix || "");
    timerId = window.setTimeout(function () { fetchDashboard(); }, delayMs);
  }

  async function fetchDashboard(options) {
    var forceRefresh = Boolean(options && options.forceRefresh);
    if (forceRefresh && syncing) return;
    if (forceRefresh) setSyncing(true);
    try {
      var response = await fetch(dashboardApiUrl(forceRefresh), {
        method: forceRefresh ? "POST" : "GET",
        headers: { Accept: "application/json" },
        cache: "no-store"
      });
      if (!response.ok) throw new Error("Dashboard refresh failed: " + response.status);
      var payload = await response.json();
      updateDashboard(payload);
      scheduleRefresh(refreshIntervalMs, "");
      if (forceRefresh) showToast("额度已同步，数据源 " + sourceLabel(payload.summary && payload.summary.source_type), false);
    } catch (error) {
      setMessageBanner("连接中断，Token BI 会自动重试并保留上次成功数据。");
      scheduleRefresh(retryIntervalMs, "重试 ");
      if (forceRefresh) showToast("同步失败，已保留上次成功数据", true);
    } finally {
      if (forceRefresh) setSyncing(false);
    }
  }

  function bindRefreshButton() {
    var refreshButton = document.querySelector("[data-refresh-link]");
    if (!refreshButton) return;
    refreshButton.addEventListener("click", function () { fetchDashboard({ forceRefresh: true }); });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") fetchDashboard();
  });

  applyStandaloneMode();
  bindRefreshButton();
  fetchDashboard();
})();
