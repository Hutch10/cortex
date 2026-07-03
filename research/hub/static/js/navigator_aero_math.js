export async function initNavigatorAeroMath(config) {
  const canvas = document.getElementById("navigator-oil-chart");
  const metaEl = document.getElementById("navigator-oil-chart-meta");
  if (!canvas || typeof Chart !== "function") {
    return;
  }

  const tenantId = String((config && config.tenantId) || "internal");
  const baselineFe = Number((config && config.baselineFe) || 38.0);
  const maxPoints = Math.max(1, Number((config && config.maxPoints) || 10000));
  const targetPoints = Math.max(200, Number((config && config.targetPoints) || 1200));

  const startedAt = performance.now();
  let reports = [];
  try {
    const params = new URLSearchParams({
      tenant_id: tenantId,
      limit: String(maxPoints),
    });
    const res = await fetch("/api/aviation/oil-reports?" + params.toString());
    const payload = await res.json();
    reports = Array.isArray(payload.reports) ? payload.reports : [];
  } catch (_err) {
    reports = [];
  }

  if (!reports.length) {
    if (metaEl) {
      metaEl.textContent = "No oil telemetry available yet.";
    }
    return;
  }

  const sampled = downsampleReports(reports, targetPoints);
  const labels = sampled.map((row) => (row.report_name || String(row.analyzed_at || "").slice(0, 10) || "Report"));
  const feData = sampled.map((row) => toNumberOrNull(row.iron));
  const cuData = sampled.map((row) => toNumberOrNull(row.copper));
  const alData = sampled.map((row) => toNumberOrNull(row.aluminium));
  const baseline = sampled.map(() => baselineFe);

  new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Fe baseline",
          data: baseline,
          borderColor: "rgba(220, 80, 60, 0.35)",
          borderDash: [6, 4],
          borderWidth: 1,
          pointRadius: 0,
          tension: 0,
        },
        {
          label: "Iron (Fe)",
          data: feData,
          borderColor: "rgba(220, 80, 60, 1)",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.15,
          spanGaps: true,
        },
        {
          label: "Copper (Cu)",
          data: cuData,
          borderColor: "rgba(45, 130, 210, 1)",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.15,
          spanGaps: true,
        },
        {
          label: "Aluminium (Al)",
          data: alData,
          borderColor: "rgba(120, 120, 120, 1)",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.15,
          spanGaps: true,
        },
      ],
    },
    options: {
      responsive: true,
      animation: false,
      parsing: false,
      normalized: true,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "top" },
        decimation: {
          enabled: true,
          algorithm: "min-max",
        },
      },
      scales: {
        y: {
          title: { display: true, text: "ppm" },
        },
        x: {
          ticks: { maxRotation: 35, autoSkip: true, maxTicksLimit: 16 },
        },
      },
    },
  });

  if (metaEl) {
    const elapsed = (performance.now() - startedAt).toFixed(1);
    metaEl.textContent = "Rendered " + sampled.length + " of " + reports.length + " points in " + elapsed + " ms.";
  }
}

function toNumberOrNull(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function downsampleReports(rows, targetPoints) {
  const count = rows.length;
  if (count <= targetPoints) {
    return rows;
  }

  const output = [];
  const step = count / targetPoints;
  let cursor = 0;
  while (Math.floor(cursor) < count) {
    output.push(rows[Math.floor(cursor)]);
    cursor += step;
  }

  const last = rows[count - 1];
  if (output[output.length - 1] !== last) {
    output.push(last);
  }
  return output;
}
