// ── Cortex Hub — shared JS utilities ───────────────────────────────────────

// Keep number inputs and their range sliders in sync
document.addEventListener("input", (e) => {
  if (e.target.type === "number") {
    const rangeId = e.target.id + "_range";
    const range   = document.getElementById(rangeId);
    if (range) range.value = e.target.value;
  }
});


// ── Billable Time Clock ────────────────────────────────────────────────────
// Tracks active UI time per tenant. Every TICK_MS of visible page time a
// pulse is sent to /api/telemetry/pulse, mirroring the background-task
// pattern defined in nerves/billing/engagement.py (lib.rs analogue).

const TICK_MS        = 10 * 60 * 1000;   // 10 minutes
const DISPLAY_KEY    = "cortex_billable_min";
const TENANT_KEY     = "cortex_active_tenant";
const TICK_START_KEY = "cortex_tick_start";

function getActiveTenant() {
  // Prefer the workflow form value if present; fall back to localStorage
  const formEl = document.getElementById("tenant_slug");
  if (formEl && formEl.value.trim()) return formEl.value.trim();
  return localStorage.getItem(TENANT_KEY) || "default";
}

function setActiveTenant(slug) {
  localStorage.setItem(TENANT_KEY, slug || "default");
}

function formatBillable(totalMinutes) {
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function updateClockDisplay(totalMinutes) {
  const el = document.getElementById("billable-display");
  if (el) el.textContent = formatBillable(totalMinutes);
}

async function fetchBillableSummary(tenantSlug) {
  try {
    const res  = await fetch(`/api/telemetry/billable?tenant_slug=${encodeURIComponent(tenantSlug)}`);
    const data = await res.json();
    const mins = data.total_minutes || 0;
    localStorage.setItem(DISPLAY_KEY, mins);
    updateClockDisplay(mins);
  } catch (_) { /* server may not be up yet on static preview */ }
}

async function sendPulse(tenantSlug) {
  const clock = document.getElementById("billable-clock");
  if (clock) clock.classList.add("ticking");

  try {
    const res  = await fetch("/api/telemetry/pulse", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ tenant_slug: tenantSlug }),
    });
    const data = await res.json();
    const mins = data.total_minutes || 0;
    localStorage.setItem(DISPLAY_KEY, mins);
    updateClockDisplay(mins);
  } catch (_) { /* offline or server restart */ }

  // Remove ticking class after the CSS transition completes
  setTimeout(() => {
    if (clock) clock.classList.remove("ticking");
  }, 600);
}

// ── Page-Visibility-aware tick engine ─────────────────────────────────────
let _tickTimer     = null;
let _tickStartedAt = null;

function _startTick() {
  if (_tickTimer) return;
  _tickStartedAt = Date.now();
  _tickTimer = setTimeout(() => {
    _tickTimer = null;
    _tickStartedAt = null;
    sendPulse(getActiveTenant()).then(() => _startTick());
  }, TICK_MS);
}

function _pauseTick() {
  if (_tickTimer) {
    clearTimeout(_tickTimer);
    _tickTimer = null;
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    _pauseTick();
  } else {
    // Resume — if we were hidden for a full tick interval, fire immediately
    _startTick();
  }
});

// ── Sync tenant slug from the workflow form in real time ──────────────────
document.addEventListener("input", (e) => {
  if (e.target.id === "tenant_slug") {
    const slug = e.target.value.trim() || "default";
    setActiveTenant(slug);
    fetchBillableSummary(slug);
  }
});

// ── Bootstrap on page load ────────────────────────────────────────────────
(function init() {
  const tenant = getActiveTenant();

  // Show cached value instantly, then refresh from server
  const cached = parseInt(localStorage.getItem(DISPLAY_KEY) || "0", 10);
  updateClockDisplay(isNaN(cached) ? 0 : cached);

  fetchBillableSummary(tenant);
  if (!document.hidden) _startTick();
})();
