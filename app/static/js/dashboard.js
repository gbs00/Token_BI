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
      return "";
    }

    var deltaMs = targetDate.getTime() - Date.now();
    if (deltaMs <= 60000) {
      return "Resets soon";
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
    return "Resets in " + parts.slice(0, 2).join(" ");
  }

  function formatUpdatedAt(targetDate) {
    if (!targetDate || Number.isNaN(targetDate.getTime())) {
      return "Waiting for first refresh";
    }

    var deltaMs = Date.now() - targetDate.getTime();
    if (deltaMs < 60000) {
      return "Updated just now";
    }

    var deltaMinutes = Math.floor(deltaMs / 60000);
    if (deltaMinutes < 60) {
      return "Updated " + deltaMinutes + " min ago";
    }

    var timeLabel = targetDate.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    });
    return "Updated at " + timeLabel;
  }

  function getTierClass(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "tier-unknown";
    }
    if (value > 75) {
      return "tier-75-plus";
    }
    if (value > 50) {
      return "tier-50-75";
    }
    if (value > 25) {
      return "tier-25-50";
    }
    return "tier-25-below";
  }

  function stateClass(state) {
    return "state-" + String(state || "empty").replace(/_/g, "-");
  }

  function stateLabel(state) {
    return String(state || "empty").replace(/_/g, " ");
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

  function updateMetric(metricType, metric) {
    var card = document.querySelector('[data-metric-card="' + metricType + '"]');
    if (!card) {
      return;
    }

    var valueNode = card.querySelector("[data-metric-value]");
    var percentNode = card.querySelector("[data-metric-percent]");
    var progressNode = card.querySelector("[data-progress-fill]");
    var resetNode = card.querySelector("[data-reset-copy]");

    var remaining = metric && metric.remaining_pct !== null && metric.remaining_pct !== undefined
      ? Number(metric.remaining_pct)
      : null;

    if (valueNode) {
      valueNode.className = "metric-value " + getTierClass(remaining);
      if (remaining === null || Number.isNaN(remaining)) {
        valueNode.textContent = "--";
      } else {
        valueNode.innerHTML =
          '<span class="metric-percent" data-metric-percent>' + remaining + '%</span>' +
          '<span class="metric-suffix">left</span>';
      }
    }

    if (progressNode) {
      progressNode.style.width = (remaining === null || Number.isNaN(remaining) ? 0 : remaining) + "%";
      progressNode.className = "progress-fill " + getTierClass(remaining);
    }

    if (resetNode) {
      if (metric && metric.reset_at) {
        resetNode.setAttribute("data-reset-at", metric.reset_at);
        resetNode.textContent = formatRelativeDuration(new Date(metric.reset_at));
      } else {
        resetNode.removeAttribute("data-reset-at");
        resetNode.textContent = "Reset time unavailable";
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

    var stateChip = document.querySelector("[data-state-chip]");
    if (stateChip) {
      stateChip.className = "status-chip " + stateClass(payload.state);
      stateChip.textContent = stateLabel(payload.state);
    }

    var liveChip = document.querySelector("[data-live-chip]");
    if (liveChip) {
      liveChip.textContent = payload.summary && payload.summary.is_estimated ? "Estimated" : "Live";
    }

    var updatedNode = document.querySelector("[data-updated-node]");
    if (updatedNode) {
      if (payload.summary && payload.summary.updated_at) {
        updatedNode.setAttribute("data-updated-at", payload.summary.updated_at);
        updatedNode.textContent = formatUpdatedAt(new Date(payload.summary.updated_at));
      } else {
        updatedNode.removeAttribute("data-updated-at");
        updatedNode.textContent = "Waiting for first refresh";
      }
    }

    var sourceNote = document.querySelector("[data-source-note]");
    if (sourceNote && payload.summary) {
      var sourceText = payload.summary.source_type || "scraped";
      if (payload.summary.source_detail && payload.summary.source_detail !== "unknown") {
        sourceText += " · " + payload.summary.source_detail;
      }
      sourceNote.textContent = sourceText;
    }

    setMessageBanner(payload.message || "");

    if (payload.metrics && payload.metrics.length) {
      payload.metrics.forEach(function (metric) {
        updateMetric(metric.metric_type, metric);
      });
    }
  }

  function startCountdown(deadlineMs, prefix) {
    var countdownNode = document.querySelector("[data-refresh-countdown]");
    if (!countdownNode) {
      return;
    }

    var label = prefix || "下次同步 ";

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
      scheduleRefresh(refreshIntervalMs, "下次同步 ");
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
