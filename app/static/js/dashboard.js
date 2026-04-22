(function () {
  var refreshIntervalMs = 180000;
  var timerId = null;
  var countdownTimerId = null;

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

  function hydrateTimestamps() {
    var updatedNode = document.querySelector("[data-updated-at]");
    if (updatedNode) {
      var updatedAt = new Date(updatedNode.getAttribute("data-updated-at"));
      updatedNode.textContent = formatUpdatedAt(updatedAt);
    }

    var resetNodes = document.querySelectorAll("[data-reset-at]");
    resetNodes.forEach(function (node) {
      var resetAt = new Date(node.getAttribute("data-reset-at"));
      var relativeLabel = formatRelativeDuration(resetAt);
      if (relativeLabel) {
        node.textContent = relativeLabel;
      }
    });
  }

  function startCountdown(deadlineMs) {
    var countdownNode = document.querySelector("[data-refresh-countdown]");
    if (!countdownNode) {
      return;
    }

    function renderCountdown() {
      var remainingMs = Math.max(deadlineMs - Date.now(), 0);
      var totalSeconds = Math.ceil(remainingMs / 1000);
      var minutes = Math.floor(totalSeconds / 60);
      var seconds = totalSeconds % 60;
      countdownNode.textContent = "Refresh in " + pad(minutes) + ":" + pad(seconds);
    }

    if (countdownTimerId) {
      window.clearInterval(countdownTimerId);
    }
    renderCountdown();
    countdownTimerId = window.setInterval(renderCountdown, 1000);
  }

  function scheduleReload() {
    if (timerId) {
      window.clearTimeout(timerId);
    }
    var deadlineMs = Date.now() + refreshIntervalMs;
    startCountdown(deadlineMs);
    timerId = window.setTimeout(function () {
      window.location.reload();
    }, refreshIntervalMs);
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      scheduleReload();
    }
  });

  hydrateTimestamps();
  scheduleReload();
})();
