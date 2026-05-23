(function () {
  var refreshIntervalMs = 180000;
  var retryIntervalMs = 15000;
  var timerId = null;
  var countdownTimerId = null;

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
      return "重置剩余未知";
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

    if (days > 0) {
      parts.push(days + "d");
    }
    if (hours > 0) {
      parts.push(hours + "h");
    }
    if (minutes > 0 && days === 0) {
      parts.push(minutes + "m");
    }
    return "重置剩余 " + parts.slice(0, 2).join(" ");
  }

  function formatUpdatedAt(targetDate) {
    if (!targetDate || Number.isNaN(targetDate.getTime())) {
      return "等待首次同步";
    }

    var deltaMs = Date.now() - targetDate.getTime();
    if (deltaMs < 60000) {
      return "刚刚同步";
    }

    var deltaMinutes = Math.floor(deltaMs / 60000);
    if (deltaMinutes < 60) {
      return deltaMinutes + " 分钟前同步";
    }

    var timeLabel = targetDate.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    });
    return timeLabel + " 同步";
  }

  function dashboardApiUrl(forceRefresh) {
    var params = new URLSearchParams(window.location.search);
    var accountId = document.body.getAttribute("data-dashboard-account-id") || params.get("account_id") || "";
    var url = forceRefresh ? "/api/v1/dashboard/refresh" : "/api/v1/dashboard";
    if (accountId) {
      url += "?account_id=" + encodeURIComponent(accountId);
    }
    return url;
  }

  function metricMinutes(metric) {
    if (!metric) {
      return null;
    }
    if (metric.window_minutes !== null && metric.window_minutes !== undefined) {
      return Number(metric.window_minutes);
    }
    if (metric.window_seconds !== null && metric.window_seconds !== undefined) {
      return Math.max(1, Math.floor(Number(metric.window_seconds) / 60));
    }
    return null;
  }

  function normalizeMetric(metric) {
    if (!metric) {
      return null;
    }

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

    if (!normalizedType) {
      return null;
    }

    return Object.assign({}, metric, {
      metric_type: normalizedType,
      label: normalizedType === "session" ? "5h 额度" : "周额度"
    });
  }

  function remainingValue(metric) {
    if (!metric || metric.remaining_pct === null || metric.remaining_pct === undefined) {
      return null;
    }
    var remaining = Number(metric.remaining_pct);
    if (Number.isNaN(remaining)) {
      return null;
    }
    return Math.max(0, Math.min(100, remaining));
  }

  function setMessageBanner(message) {
    var banner = document.querySelector("[data-message-banner]");
    if (!message) {
      if (banner) {
        banner.remove();
      }
      return;
    }

    if (!banner) {
      var supportRow = document.querySelector(".support-row");
      if (!supportRow || !supportRow.parentNode) {
        return;
      }
      banner = document.createElement("div");
      banner.className = "message-banner";
      banner.setAttribute("data-message-banner", "true");
      supportRow.parentNode.insertBefore(banner, supportRow.nextSibling);
    }
    banner.textContent = message;
  }

  function ensureMetricList() {
    var list = document.querySelector("[data-metric-list]");
    if (list) {
      return list;
    }

    var card = document.querySelector(".dashboard-card");
    if (!card) {
      return null;
    }
    list = document.createElement("div");
    list.className = "metric-list";
    list.setAttribute("data-metric-list", "true");
    card.appendChild(list);
    return list;
  }

  function createMetricCard(metric) {
    var list = ensureMetricList();
    if (!list || !metric || !metric.metric_type) {
      return null;
    }

    var card = document.createElement("article");
    card.className = "metric-card metric-" + metric.metric_type;
    card.setAttribute("data-metric-card", metric.metric_type);
    card.innerHTML =
      '<div class="metric-head">' +
        '<div>' +
          '<h2 class="metric-title" data-metric-title></h2>' +
        '</div>' +
      '</div>' +
      '<div class="radial-wrap">' +
        '<div class="metric-radial" data-metric-radial>' +
          '<div class="metric-radial-inner">' +
            '<strong data-metric-percent>--</strong>' +
            '<span>剩余额度</span>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="quota-footer">' +
        '<span class="reset-copy" data-reset-copy>重置剩余未知</span>' +
      '</div>';
    list.appendChild(card);
    return card;
  }

  function syncMetricCards(metrics) {
    var safeMetrics = Array.isArray(metrics)
      ? metrics.map(normalizeMetric).filter(Boolean)
      : [];
    var wanted = {};
    safeMetrics.forEach(function (metric) {
      wanted[metric.metric_type] = true;
      var existing = document.querySelector('[data-metric-card="' + metric.metric_type + '"]');
      if (!existing) {
        createMetricCard(metric);
      }
    });

    Array.prototype.forEach.call(document.querySelectorAll("[data-metric-card]"), function (card) {
      var metricType = card.getAttribute("data-metric-card");
      if (!wanted[metricType]) {
        card.remove();
      }
    });

    var list = document.querySelector("[data-metric-list]");
    if (list && safeMetrics.length === 0) {
      list.remove();
    }
    return safeMetrics;
  }

  function updateMetric(metricType, metric) {
    var normalized = normalizeMetric(metric);
    if (!normalized) {
      return;
    }

    var card = document.querySelector('[data-metric-card="' + metricType + '"]');
    if (!card) {
      card = createMetricCard(normalized);
      if (!card) {
        return;
      }
    }

    var titleNode = card.querySelector("[data-metric-title]");
    var radialNode = card.querySelector("[data-metric-radial]");
    var percentNode = card.querySelector("[data-metric-percent]");
    var resetNode = card.querySelector("[data-reset-copy]");
    var remaining = remainingValue(normalized);

    card.className = "metric-card metric-" + normalized.metric_type;
    card.setAttribute("data-metric-card", normalized.metric_type);
    card.style.setProperty("--remaining-pct", (remaining === null ? 0 : remaining) + "%");
    card.style.setProperty("--remaining-deg", (remaining === null ? 0 : remaining * 3.6) + "deg");

    if (titleNode) {
      titleNode.textContent = normalized.label;
    }

    if (radialNode) {
      radialNode.setAttribute("aria-label", normalized.label + "剩余 " + (remaining === null ? "未知" : remaining + "%"));
    }

    if (percentNode) {
      percentNode.textContent = remaining === null ? "--" : remaining + "%";
    }

    if (resetNode) {
      if (normalized.reset_at) {
        resetNode.setAttribute("data-reset-at", normalized.reset_at);
        resetNode.textContent = formatRelativeDuration(new Date(normalized.reset_at));
      } else {
        resetNode.removeAttribute("data-reset-at");
        resetNode.textContent = "重置剩余未知";
      }
    }
  }

  function updateDashboard(payload) {
    if (!payload) {
      return;
    }

    if (payload.account && payload.account.account_id) {
      document.body.setAttribute("data-dashboard-account-id", payload.account.account_id);
    }

    var accountName = document.querySelector("[data-account-name]");
    if (accountName) {
      accountName.textContent = payload.account && payload.account.masked_email
        ? payload.account.masked_email
        : "No active account selected";
    }

    var updatedNode = document.querySelector("[data-updated-node]");
    if (updatedNode) {
      if (payload.summary && payload.summary.updated_at) {
        updatedNode.setAttribute("data-updated-at", payload.summary.updated_at);
        updatedNode.textContent = formatUpdatedAt(new Date(payload.summary.updated_at));
      } else {
        updatedNode.removeAttribute("data-updated-at");
        updatedNode.textContent = "等待首次同步";
      }
    }

    var sourceNote = document.querySelector("[data-source-note]");
    if (sourceNote && payload.summary) {
      var sourceText = payload.summary.source_type || "本机服务";
      if (payload.summary.source_detail && payload.summary.source_detail !== "unknown") {
        sourceText += " · " + payload.summary.source_detail;
      }
      sourceNote.textContent = sourceText;
    }

    setMessageBanner(payload.message || "");

    var normalizedMetrics = syncMetricCards(payload.metrics || []);
    normalizedMetrics.forEach(function (metric) {
      updateMetric(metric.metric_type, metric);
    });
  }

  function startCountdown(deadlineMs, prefix) {
    var countdownNode = document.querySelector("[data-refresh-countdown]");
    if (!countdownNode) {
      return;
    }

    var label = prefix || "";

    function renderCountdown() {
      var remainingMs = Math.max(deadlineMs - Date.now(), 0);
      var totalSeconds = Math.ceil(remainingMs / 1000);
      var minutes = Math.floor(totalSeconds / 60);
      var seconds = totalSeconds % 60;
      countdownNode.textContent = label + pad(minutes) + ":" + pad(seconds);
    }

    if (countdownTimerId) {
      window.clearInterval(countdownTimerId);
    }
    renderCountdown();
    countdownTimerId = window.setInterval(renderCountdown, 1000);
  }

  function scheduleRefresh(delayMs, prefix) {
    if (timerId) {
      window.clearTimeout(timerId);
    }
    var deadlineMs = Date.now() + delayMs;
    startCountdown(deadlineMs, prefix);
    timerId = window.setTimeout(function () {
      fetchDashboard();
    }, delayMs);
  }

  async function fetchDashboard(options) {
    var forceRefresh = Boolean(options && options.forceRefresh);
    try {
      var response = await fetch(dashboardApiUrl(forceRefresh), {
        method: forceRefresh ? "POST" : "GET",
        headers: { Accept: "application/json" },
        cache: "no-store"
      });

      if (!response.ok) {
        throw new Error("Dashboard refresh failed: " + response.status);
      }

      var payload = await response.json();
      updateDashboard(payload);
      scheduleRefresh(refreshIntervalMs, "");
    } catch (error) {
      setMessageBanner("连接中断，Token BI 会自动重试。");
      scheduleRefresh(retryIntervalMs, "重试 ");
    }
  }

  function bindRefreshButton() {
    var refreshLink = document.querySelector("[data-refresh-link]");
    if (!refreshLink) {
      return;
    }
    refreshLink.addEventListener("click", function (event) {
      event.preventDefault();
      fetchDashboard({ forceRefresh: true });
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      fetchDashboard();
    }
  });

  applyStandaloneMode();
  bindRefreshButton();
  fetchDashboard();
})();
