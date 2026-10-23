/**
 * Cloud-Based Notification System — Client-Side Application Controller
 * Handles real-time polling, metrics synchronization, asynchronous submissions,
 * status filtering, demo presets, modals, and theme management.
 */

class CloudNotifyApp {
  constructor() {
    // State
    this.currentStatusFilter = "ALL";
    this.searchQuery = "";
    this.autoRefreshInterval = null;
    this.pollIntervalMs = 3000;
    this.isPolling = false;
    this.cachedNotifications = [];

    // Initialize DOM references and listeners
    this.initElements();
    this.initTheme();
    this.initEventListeners();

    // Initial Data Fetch
    this.fetchDashboardData();
    this.startAutoRefresh();
  }

  /* ------------------------------------------------------------------------
     DOM Elements Initialization
     ------------------------------------------------------------------------ */
  initElements() {
    // Theme
    this.htmlEl = document.documentElement;
    this.themeToggleBtn = document.getElementById("themeToggleBtn");

    // Auto Refresh & Sync
    this.autoRefreshToggle = document.getElementById("autoRefreshToggle");
    this.headerRefreshBtn = document.getElementById("headerRefreshBtn");
    this.sidebarRefreshBtn = document.getElementById("sidebarRefreshBtn");
    this.tableRefreshBtn = document.getElementById("tableRefreshBtn");
    this.lastSyncTime = document.getElementById("lastSyncTime");

    // Stat Cards
    this.statTotal = document.getElementById("statTotal");
    this.statSent = document.getElementById("statSent");
    this.statPending = document.getElementById("statPending");
    this.statProcessing = document.getElementById("statProcessing");
    this.statFailed = document.getElementById("statFailed");
    this.statQueueBacklog = document.getElementById("statQueueBacklog");

    // Form
    this.form = document.getElementById("notificationForm");
    this.recipientEmail = document.getElementById("recipientEmail");
    this.notificationSubject = document.getElementById("notificationSubject");
    this.notificationMessage = document.getElementById("notificationMessage");
    this.submitBtn = document.getElementById("submitBtn");
    this.submitSpinner = document.getElementById("submitSpinner");
    this.submitBtnText = document.getElementById("submitBtnText");
    this.resetFormBtn = document.getElementById("resetFormBtn");
    this.formAlert = document.getElementById("formAlert");
    this.emailError = document.getElementById("emailError");
    this.subjectError = document.getElementById("subjectError");
    this.messageError = document.getElementById("messageError");
    this.subjectCharCount = document.getElementById("subjectCharCount");
    this.messageCharCount = document.getElementById("messageCharCount");

    // Presets
    this.presetChips = document.querySelectorAll(".preset-chip");

    // Table & Filters
    this.notificationsTbody = document.getElementById("notificationsTbody");
    this.tableInfo = document.getElementById("tableInfo");
    this.searchInput = document.getElementById("searchInput");
    this.searchClearBtn = document.getElementById("searchClearBtn");
    this.filterPills = document.querySelectorAll(".filter-pill");

    // Modals & Detail View
    this.detailModal = document.getElementById("detailModal");
    this.modalCloseBtn = document.getElementById("modalCloseBtn");
    this.modalDismissBtn = document.getElementById("modalDismissBtn");
    this.modalRetryBtn = document.getElementById("modalRetryBtn");
    this.modalId = document.getElementById("modalId");
    this.modalStatusBadge = document.getElementById("modalStatusBadge");
    this.modalEmail = document.getElementById("modalEmail");
    this.modalSubject = document.getElementById("modalSubject");
    this.modalMessage = document.getElementById("modalMessage");
    this.modalCreatedAt = document.getElementById("modalCreatedAt");
    this.modalSentAt = document.getElementById("modalSentAt");
    this.modalErrorItem = document.getElementById("modalErrorItem");
    this.modalError = document.getElementById("modalError");
    this.modalJson = document.getElementById("modalJson");

    // Sidebar & Status
    this.sidebar = document.getElementById("sidebar");
    this.mobileMenuBtn = document.getElementById("mobileMenuBtn");
    this.mobileCloseBtn = document.getElementById("mobileCloseBtn");
    this.systemHealthBadge = document.getElementById("systemHealthBadge");
    this.systemHealthText = document.getElementById("systemHealthText");
    this.systemRedisSub = document.getElementById("systemRedisSub");
    this.badgeRedisStatus = document.getElementById("badgeRedisStatus");
    this.sidebarResetBtn = document.getElementById("sidebarResetBtn");
    this.bannerDismissBtn = document.getElementById("bannerDismissBtn");
    this.toastContainer = document.getElementById("toastContainer");
  }

  /* ------------------------------------------------------------------------
     Theme Management
     ------------------------------------------------------------------------ */
  initTheme() {
    const savedTheme = localStorage.getItem("cloudnotify_theme") || "dark";
    this.htmlEl.setAttribute("data-theme", savedTheme);
  }

  toggleTheme() {
    const current = this.htmlEl.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    this.htmlEl.setAttribute("data-theme", next);
    localStorage.setItem("cloudnotify_theme", next);
    this.showToast(`Switched to ${next} mode`, "info");
  }

  /* ------------------------------------------------------------------------
     Event Listeners
     ------------------------------------------------------------------------ */
  initEventListeners() {
    // Theme Switcher
    this.themeToggleBtn.addEventListener("click", () => this.toggleTheme());

    // Mobile Sidebar Drawer
    this.mobileMenuBtn.addEventListener("click", () => this.sidebar.classList.add("open"));
    this.mobileCloseBtn.addEventListener("click", () => this.sidebar.classList.remove("open"));

    // Banner Dismiss
    if (this.bannerDismissBtn) {
      this.bannerDismissBtn.addEventListener("click", (e) => {
        e.target.closest(".simulation-banner").style.display = "none";
      });
    }

    // Refresh triggers
    const triggerRefresh = () => {
      this.fetchDashboardData(true);
      this.showToast("Telemetry data refreshed", "info");
    };
    this.headerRefreshBtn.addEventListener("click", triggerRefresh);
    this.sidebarRefreshBtn.addEventListener("click", triggerRefresh);
    this.tableRefreshBtn.addEventListener("click", triggerRefresh);

    // Auto-refresh switch
    this.autoRefreshToggle.addEventListener("change", (e) => {
      if (e.target.checked) {
        this.startAutoRefresh();
        this.showToast("Live Sync enabled (3s)", "info");
      } else {
        this.stopAutoRefresh();
        this.showToast("Live Sync paused", "warning");
      }
    });

    // Form Character Counters
    this.notificationSubject.addEventListener("input", (e) => {
      this.subjectCharCount.textContent = `${e.target.value.length}/200`;
      this.clearFieldError("subject");
    });

    this.notificationMessage.addEventListener("input", (e) => {
      this.messageCharCount.textContent = `${e.target.value.length}/5000`;
      this.clearFieldError("message");
    });

    this.recipientEmail.addEventListener("input", () => this.clearFieldError("email"));

    // Reset Form button
    this.resetFormBtn.addEventListener("click", () => this.resetForm());

    // Submit Notification Form
    this.form.addEventListener("submit", (e) => this.handleFormSubmit(e));

    // Preset Buttons
    this.presetChips.forEach((chip) => {
      chip.addEventListener("click", () => this.applyPreset(chip.dataset.preset));
    });

    // Status Filter Pills
    this.filterPills.forEach((pill) => {
      pill.addEventListener("click", () => {
        this.filterPills.forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        this.currentStatusFilter = pill.dataset.status;
        this.renderTableRows();
      });
    });

    // Search Input with Debounce
    let searchDebounce = null;
    this.searchInput.addEventListener("input", (e) => {
      clearTimeout(searchDebounce);
      this.searchQuery = e.target.value.trim().toLowerCase();
      this.searchClearBtn.classList.toggle("hidden", this.searchQuery.length === 0);
      searchDebounce = setTimeout(() => this.renderTableRows(), 200);
    });

    this.searchClearBtn.addEventListener("click", () => {
      this.searchInput.value = "";
      this.searchQuery = "";
      this.searchClearBtn.classList.add("hidden");
      this.renderTableRows();
    });

    // Modal Close
    this.modalCloseBtn.addEventListener("click", () => this.closeModal());
    this.modalDismissBtn.addEventListener("click", () => this.closeModal());
    this.detailModal.addEventListener("click", (e) => {
      if (e.target === this.detailModal) this.closeModal();
    });

    // Demo Data Reset
    this.sidebarResetBtn.addEventListener("click", () => this.handleResetData());
  }

  /* ------------------------------------------------------------------------
     Presets Setup
     ------------------------------------------------------------------------ */
  applyPreset(type) {
    const presets = {
      welcome: {
        email: "alice.cooper@university.edu",
        subject: "Welcome to Cloud Computing Portal 2026",
        message: "Hello Alice,\n\nWelcome to your cloud notification environment! Your account has been provisioned successfully.",
      },
      otp: {
        email: "security.audit@cloudlab.org",
        subject: "Security Verification Code [OTP]",
        message: "Your one-time passkey is 849-210. Valid for the next 10 minutes. Do not share this credential with anyone.",
      },
      alert: {
        email: "devops-alerts@infra.io",
        subject: "High Memory Threshold Exceeded on Cluster worker-node-02",
        message: "Cloud Monitoring Alert:\nNode: worker-node-02\nCPU Usage: 94.8%\nMemory Usage: 88.2%\nAction: Dynamic worker autoscale recommended.",
      },
      failure: {
        email: "fail-test@reject.domain.com",
        subject: "Simulate Delivery Failure [Trigger Test]",
        message: "This notification is configured with a failure trigger keyword ('fail') to test the worker error handling and retry mechanism.",
      },
    };

    const data = presets[type];
    if (data) {
      this.recipientEmail.value = data.email;
      this.notificationSubject.value = data.subject;
      this.notificationMessage.value = data.message;
      this.subjectCharCount.textContent = `${data.subject.length}/200`;
      this.messageCharCount.textContent = `${data.message.length}/5000`;
      this.clearAllErrors();
      this.showToast(`Applied preset: ${type.toUpperCase()}`, "info");
    }
  }

  /* ------------------------------------------------------------------------
     Form Validation & Submission
     ------------------------------------------------------------------------ */
  validateForm() {
    let isValid = true;
    this.clearAllErrors();

    const email = this.recipientEmail.value.trim();
    const subject = this.notificationSubject.value.trim();
    const message = this.notificationMessage.value.trim();

    // Email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!email) {
      this.showFieldError("email", "Recipient email is required.");
      isValid = false;
    } else if (!emailRegex.test(email)) {
      this.showFieldError("email", "Please enter a valid email (e.g. user@example.com).");
      isValid = false;
    }

    // Subject validation
    if (!subject) {
      this.showFieldError("subject", "Subject line cannot be empty.");
      isValid = false;
    } else if (subject.length > 200) {
      this.showFieldError("subject", "Subject exceeds maximum 200 characters.");
      isValid = false;
    }

    // Message validation
    if (!message) {
      this.showFieldError("message", "Notification message content is required.");
      isValid = false;
    }

    return isValid;
  }

  showFieldError(field, msg) {
    if (field === "email") this.emailError.textContent = msg;
    if (field === "subject") this.subjectError.textContent = msg;
    if (field === "message") this.messageError.textContent = msg;
  }

  clearFieldError(field) {
    if (field === "email") this.emailError.textContent = "";
    if (field === "subject") this.subjectError.textContent = "";
    if (field === "message") this.messageError.textContent = "";
  }

  clearAllErrors() {
    this.emailError.textContent = "";
    this.subjectError.textContent = "";
    this.messageError.textContent = "";
    this.formAlert.classList.add("hidden");
  }

  async handleFormSubmit(e) {
    e.preventDefault();
    if (!this.validateForm()) return;

    const payload = {
      email: this.recipientEmail.value.trim(),
      subject: this.notificationSubject.value.trim(),
      message: this.notificationMessage.value.trim(),
    };

    // UI Loading state
    this.setSubmitLoading(true);

    try {
      const response = await fetch("/send-notification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const result = await response.json();

      if (response.ok && result.success) {
        this.showToast("Notification successfully accepted & enqueued!", "success");
        this.showFormAlert(
          `Notification #${result.notification_id.substring(0, 8)} successfully queued into Redis! Status: PENDING`,
          "success"
        );
        this.resetForm();
        // Immediately fetch data to reflect the new record
        this.fetchDashboardData(true);
      } else {
        const errorMsg = result.error || "Failed to submit notification.";
        this.showToast(errorMsg, "error");
        this.showFormAlert(errorMsg, "error");
      }
    } catch (err) {
      const networkError = "Network error: Unable to contact Flask API server.";
      this.showToast(networkError, "error");
      this.showFormAlert(networkError, "error");
    } finally {
      this.setSubmitLoading(false);
    }
  }

  setSubmitLoading(isLoading) {
    this.submitBtn.disabled = isLoading;
    if (isLoading) {
      this.submitSpinner.classList.remove("hidden");
      this.submitBtnText.textContent = "Queueing...";
    } else {
      this.submitSpinner.classList.add("hidden");
      this.submitBtnText.textContent = "Send Notification";
    }
  }

  showFormAlert(message, type) {
    this.formAlert.className = `form-alert ${type}`;
    this.formAlert.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="8" x2="12" y2="12"></line>
        <line x1="12" y1="16" x2="12.01" y2="16"></line>
      </svg>
      <span>${this.escapeHtml(message)}</span>
    `;
    this.formAlert.classList.remove("hidden");
  }

  resetForm() {
    this.form.reset();
    this.subjectCharCount.textContent = "0/200";
    this.messageCharCount.textContent = "0/5000";
    this.clearAllErrors();
  }

  /* ------------------------------------------------------------------------
     Data Polling & Metrics Synchronization
     ------------------------------------------------------------------------ */
  startAutoRefresh() {
    this.stopAutoRefresh();
    this.autoRefreshInterval = setInterval(() => {
      this.fetchDashboardData(false);
    }, this.pollIntervalMs);
  }

  stopAutoRefresh() {
    if (this.autoRefreshInterval) {
      clearInterval(this.autoRefreshInterval);
      this.autoRefreshInterval = null;
    }
  }

  async fetchDashboardData(isManual = false) {
    if (this.isPolling) return;
    this.isPolling = true;

    try {
      // Parallel fetch for notifications list and health
      const [notifRes, healthRes] = await Promise.all([
        fetch("/notifications"),
        fetch("/health"),
      ]);

      if (notifRes.ok) {
        const notifData = await notifRes.json();
        if (notifData.success) {
          this.cachedNotifications = notifData.notifications || [];
          this.updateMetrics(notifData.counts, notifData.queue);
          this.renderTableRows();
        }
      }

      if (healthRes.ok) {
        const healthData = await healthRes.json();
        this.updateHealthStatus(healthData);
      }

      // Update last sync timestamp
      const now = new Date();
      this.lastSyncTime.textContent = `Synced: ${now.toLocaleTimeString()}`;
    } catch (err) {
      console.warn("Telemetry polling warning:", err);
      this.updateOfflineHealth();
    } finally {
      this.isPolling = false;
    }
  }

  updateMetrics(counts = {}, queue = {}) {
    const total = counts.total || 0;
    const sent = counts.sent || 0;
    const pending = counts.pending || 0;
    const processing = counts.processing || 0;
    const failed = counts.failed || 0;
    const backlog = queue.waiting || 0;

    this.animateNumber(this.statTotal, total);
    this.animateNumber(this.statSent, sent);
    this.animateNumber(this.statPending, pending);
    this.animateNumber(this.statProcessing, processing);
    this.animateNumber(this.statFailed, failed);
    this.animateNumber(this.statQueueBacklog, backlog);
  }

  animateNumber(el, target) {
    if (!el) return;
    const current = parseInt(el.textContent, 10) || 0;
    if (current === target) return;

    const diff = target - current;
    const steps = 10;
    let step = 0;

    const timer = setInterval(() => {
      step++;
      const val = Math.round(current + (diff * (step / steps)));
      el.textContent = val;
      if (step >= steps) {
        el.textContent = target;
        clearInterval(timer);
      }
    }, 20);
  }

  updateHealthStatus(healthData) {
    const isHealthy = healthData.status === "healthy";
    const redisConnected = healthData.services?.message_queue?.status === "connected";

    // Sidebar status badge
    this.systemHealthText.textContent = isHealthy ? "System: Healthy" : "System: Degraded";
    this.systemRedisSub.textContent = redisConnected ? "Redis: Connected" : "Redis: Disconnected";

    const dot = this.systemHealthBadge.querySelector(".status-indicator-dot");
    if (dot) {
      dot.className = `status-indicator-dot ${isHealthy ? "online" : redisConnected ? "degraded" : "offline"}`;
    }

    // Queue telemetry badge
    if (this.badgeRedisStatus) {
      this.badgeRedisStatus.className = `badge ${redisConnected ? "badge-success" : "badge-failed"}`;
      this.badgeRedisStatus.textContent = redisConnected ? "Connected (Port 6379)" : "Unreachable";
    }
  }

  updateOfflineHealth() {
    this.systemHealthText.textContent = "System: Offline";
    this.systemRedisSub.textContent = "API Server Unreachable";
    const dot = this.systemHealthBadge.querySelector(".status-indicator-dot");
    if (dot) dot.className = "status-indicator-dot offline";
  }

  /* ------------------------------------------------------------------------
     Table Rendering & Filtering
     ------------------------------------------------------------------------ */
  renderTableRows() {
    const filtered = this.cachedNotifications.filter((item) => {
      // Status filter
      if (this.currentStatusFilter !== "ALL" && item.status !== this.currentStatusFilter) {
        return false;
      }
      // Search query filter
      if (this.searchQuery) {
        const emailMatch = (item.email || "").toLowerCase().includes(this.searchQuery);
        const subjectMatch = (item.subject || "").toLowerCase().includes(this.searchQuery);
        const idMatch = (item.id || "").toLowerCase().includes(this.searchQuery);
        if (!emailMatch && !subjectMatch && !idMatch) return false;
      }
      return true;
    });

    this.tableInfo.textContent = `Showing ${filtered.length} of ${this.cachedNotifications.length} notifications`;

    if (filtered.length === 0) {
      this.notificationsTbody.innerHTML = `
        <tr class="empty-state-row">
          <td colspan="6">
            <div class="empty-state">
              <div class="empty-icon">📭</div>
              <div class="empty-title">No Notifications Found</div>
              <div class="empty-desc">
                ${this.cachedNotifications.length === 0 
                  ? "No notification requests have been submitted yet. Use the composer form above to send one!" 
                  : "No items match your active search and status filter."}
              </div>
            </div>
          </td>
        </tr>
      `;
      return;
    }

    this.notificationsTbody.innerHTML = filtered
      .map((item) => {
        const badgeHtml = this.getStatusBadgeHtml(item.status);
        const formattedCreated = this.formatTimeAgo(item.created_at);
        const formattedSent = item.sent_at ? this.formatTimeAgo(item.sent_at) : "<span class='text-muted'>--</span>";
        const isFailed = item.status === "FAILED";

        return `
          <tr data-id="${item.id}">
            <td>${badgeHtml}</td>
            <td class="recipient-cell">${this.escapeHtml(item.email)}</td>
            <td class="subject-cell" title="${this.escapeHtml(item.subject)}">${this.escapeHtml(item.subject)}</td>
            <td class="timestamp-cell" title="${item.created_at}">${formattedCreated}</td>
            <td class="timestamp-cell" title="${item.sent_at || ''}">${formattedSent}</td>
            <td class="actions-cell">
              <button class="btn-table-action" onclick="app.openDetailModal('${item.id}')">View</button>
              ${isFailed ? `<button class="btn-table-action retry-btn" onclick="app.retryNotification('${item.id}')">Retry</button>` : ""}
            </td>
          </tr>
        `;
      })
      .join("");
  }

  getStatusBadgeHtml(status) {
    switch (status) {
      case "PENDING":
        return `<span class="badge badge-pending"><span class="badge-dot"></span>Pending</span>`;
      case "PROCESSING":
        return `<span class="badge badge-processing"><span class="badge-dot"></span>Processing</span>`;
      case "SENT":
        return `<span class="badge badge-sent"><span class="badge-dot"></span>Sent (Simulated)</span>`;
      case "FAILED":
        return `<span class="badge badge-failed"><span class="badge-dot"></span>Failed</span>`;
      default:
        return `<span class="badge">${this.escapeHtml(status)}</span>`;
    }
  }

  /* ------------------------------------------------------------------------
     Modal Inspection & Retry Logic
     ------------------------------------------------------------------------ */
  openDetailModal(id) {
    const item = this.cachedNotifications.find((n) => n.id === id);
    if (!item) return;

    this.modalId.textContent = `ID: ${item.id}`;
    this.modalStatusBadge.innerHTML = this.getStatusBadgeHtml(item.status);
    this.modalEmail.textContent = item.email;
    this.modalSubject.textContent = item.subject;
    this.modalMessage.textContent = item.message;
    this.modalCreatedAt.textContent = item.created_at || "N/A";
    this.modalSentAt.textContent = item.sent_at || "Not dispatched yet";

    // Error Box
    if (item.status === "FAILED" && item.error) {
      this.modalError.textContent = item.error;
      this.modalErrorItem.classList.remove("hidden");
      this.modalRetryBtn.classList.remove("hidden");
      this.modalRetryBtn.onclick = () => {
        this.retryNotification(item.id);
        this.closeModal();
      };
    } else {
      this.modalErrorItem.classList.add("hidden");
      this.modalRetryBtn.classList.add("hidden");
    }

    // JSON Dump
    this.modalJson.textContent = JSON.stringify(item, null, 2);

    this.detailModal.classList.remove("hidden");
  }

  closeModal() {
    this.detailModal.classList.add("hidden");
  }

  async retryNotification(id) {
    try {
      const response = await fetch(`/retry-notification/${id}`, { method: "POST" });
      const result = await response.json();
      if (response.ok && result.success) {
        this.showToast(`Task ${id.substring(0, 8)} re-enqueued for delivery!`, "success");
        this.fetchDashboardData(true);
      } else {
        this.showToast(result.error || "Failed to retry task.", "error");
      }
    } catch (err) {
      this.showToast("Network error retrying notification.", "error");
    }
  }

  async handleResetData() {
    if (!confirm("Are you sure you want to clear all notification records for demo reset?")) {
      return;
    }

    try {
      const res = await fetch("/api/clear-history", { method: "POST" });
      const data = await res.json();
      if (res.ok && data.success) {
        this.showToast("Demo notification data cleared successfully.", "info");
        this.fetchDashboardData(true);
      } else {
        this.showToast("Failed to clear data.", "error");
      }
    } catch (e) {
      this.showToast("Failed to clear demo data.", "error");
    }
  }

  /* ------------------------------------------------------------------------
     Toast & Utilities
     ------------------------------------------------------------------------ */
  showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${this.escapeHtml(message)}</span>`;
    this.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(50px)";
      setTimeout(() => toast.remove(), 250);
    }, 3500);
  }

  formatTimeAgo(isoString) {
    if (!isoString) return "--";
    try {
      const date = new Date(isoString);
      const diffSec = Math.floor((new Date() - date) / 1000);
      if (diffSec < 5) return "Just now";
      if (diffSec < 60) return `${diffSec}s ago`;
      const diffMin = Math.floor(diffSec / 60);
      if (diffMin < 60) return `${diffMin}m ago`;
      const diffHour = Math.floor(diffMin / 60);
      if (diffHour < 24) return `${diffHour}h ago`;
      return date.toLocaleDateString();
    } catch {
      return isoString;
    }
  }

  escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
}

// Instantiate on DOM load
document.addEventListener("DOMContentLoaded", () => {
  window.app = new CloudNotifyApp();
});
