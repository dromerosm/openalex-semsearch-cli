"use strict";

// Distinct cluster colors; outliers are rendered gray.
const PALETTE = ["#58a6ff", "#3fb950", "#f0c674", "#bc8cff", "#ff7b72", "#39c5cf", "#db61a2", "#e3b341"];
const NOISE_COLOR = "#6e7681";

// ---------------------------------------------------------------- helpers
const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (v != null) n.setAttribute(k, v);
  }
  for (const kid of kids) n.append(kid?.nodeType ? kid : document.createTextNode(kid ?? ""));
  return n;
};
const fmtFwci = (v) => (v == null ? "—" : v >= 100 ? String(Math.round(v)) : v.toFixed(1));
const fmtPct = (v) => (v == null ? "—" : Math.round(v * 100) + "%");
const truncate = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + "…" : s || "");

// ---------------------------------------------------------------- live search
let lastResults = [];
let sortState = { key: "relevance", dir: -1 };

const COLUMNS = [
  { key: "i", label: "#", num: true, sortable: false },
  { key: "title", label: "Title", sortable: false },
  { key: "year", label: "Year", num: true, sortable: true },
  { key: "cited_by_count", label: "Cites", num: true, sortable: true },
  { key: "fwci", label: "FWCI", num: true, sortable: true },
  { key: "percentile", label: "Pctl", num: true, sortable: true },
  { key: "field", label: "Field", sortable: false },
  { key: "topic", label: "Topic", sortable: false },
];

function renderTable() {
  const results = $("#results");
  results.replaceChildren();
  if (!lastResults.length) return;

  const rows = [...lastResults];
  const { key, dir } = sortState;
  rows.sort((a, b) => {
    const av = a[key] ?? -Infinity, bv = b[key] ?? -Infinity;
    return av < bv ? -dir : av > bv ? dir : 0;
  });

  const thead = el("thead");
  const htr = el("tr");
  for (const col of COLUMNS) {
    const th = el("th", { class: (col.num ? "num " : "") + (col.sortable ? "sortable" : "") },
      col.label + (col.sortable && sortState.key === col.key ? (dir === -1 ? " ↓" : " ↑") : ""));
    if (col.sortable) th.onclick = () => {
      sortState = { key: col.key, dir: sortState.key === col.key ? -sortState.dir : -1 };
      renderTable();
    };
    htr.append(th);
  }
  thead.append(htr);

  const tbody = el("tbody");
  rows.forEach((w, idx) => {
    const tr = el("tr");
    tr.append(el("td", { class: "num" }, String(idx + 1)));

    // title cell with link + authors
    const href = w.doi || w.id;
    const titleCell = el("td", { class: "title-cell" });
    titleCell.append(el("a", { href, target: "_blank", rel: "noopener" }, w.title));
    const authors = (w.authors || []).slice(0, 3).join(", ") + ((w.authors || []).length > 3 ? " et al." : "");
    titleCell.append(el("div", { class: "meta" }, [authors, w.source].filter(Boolean).join(" · ")));
    tr.append(titleCell);

    tr.append(el("td", { class: "num" }, w.year ?? "—"));
    tr.append(el("td", { class: "num" }, (w.cited_by_count ?? 0).toLocaleString()));
    tr.append(el("td", { class: "num" }, fmtFwci(w.fwci)));

    const pct = el("td", { class: "num" }, fmtPct(w.percentile) + " ");
    if (w.is_top_1_percent) pct.append(el("span", { class: "star", title: "Top 1%" }, "★"));
    else if (w.is_top_10_percent) pct.append(el("span", { class: "tri", title: "Top 10%" }, "▲"));
    tr.append(pct);

    tr.append(el("td", {}, w.field || "—"));
    tr.append(el("td", {}, truncate(w.topic, 32) || "—"));
    tbody.append(tr);
  });

  results.append(el("table", {}, thead, tbody));
}

async function doSearch(ev) {
  ev?.preventDefault();
  const q = $("#q").value.trim();
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const status = $("#search-status");
  if (!q) { status.textContent = "Type a query."; return; }

  $("#search-btn").disabled = true;
  status.className = "status";
  status.textContent = "Searching OpenAlex…";
  try {
    const r = await fetch(`/api/search?q=${encodeURIComponent(q)}&mode=${mode}`);
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    lastResults = data.results;
    sortState = { key: "relevance", dir: -1 };
    renderTable();
    status.textContent = `${data.count} result${data.count === 1 ? "" : "s"} · ${mode}` + (data.cached ? " · cached" : "");
    if (!data.count) status.textContent += " — no impactful papers found, try another query.";
  } catch (e) {
    status.className = "status error";
    status.textContent = "Error: " + e.message;
  } finally {
    $("#search-btn").disabled = false;
  }
}

// ---------------------------------------------------------------- cluster explorer
function clusterColors(clusters) {
  const map = {};
  let i = 0;
  for (const c of clusters) map[c.label] = c.is_noise ? NOISE_COLOR : PALETTE[i++ % PALETTE.length];
  return map;
}
const clusterName = (c) => (c.is_noise ? "Outliers" : `Cluster ${c.label}`);

function renderPlot(data, colors) {
  const maxCites = Math.max(1, ...data.points.map((p) => p.cited_by_count));
  const traces = data.clusters.map((c) => {
    const pts = data.points.filter((p) => p.cluster === c.label);
    return {
      x: pts.map((p) => p.x),
      y: pts.map((p) => p.y),
      mode: "markers",
      type: "scatter",
      name: `${clusterName(c)} (${c.size})`,
      marker: {
        color: colors[c.label],
        size: pts.map((p) => 7 + 20 * Math.sqrt(p.cited_by_count) / Math.sqrt(maxCites)),
        line: { width: 0.5, color: "#0d1117" },
        opacity: c.is_noise ? 0.5 : 0.9,
      },
      customdata: pts.map((p) => [truncate(p.title, 70), p.cited_by_count.toLocaleString(), fmtFwci(p.fwci), p.field || "—"]),
      hovertemplate: "<b>%{customdata[0]}</b><br>cites %{customdata[1]} · FWCI %{customdata[2]}<br>%{customdata[3]}<extra></extra>",
    };
  });

  const layout = {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "#8b949e", size: 12 },
    margin: { l: 10, r: 10, t: 10, b: 10 },
    xaxis: { showgrid: false, zeroline: false, showticklabels: false },
    yaxis: { showgrid: false, zeroline: false, showticklabels: false },
    legend: { bgcolor: "rgba(0,0,0,0)", font: { size: 11 } },
    hoverlabel: { bgcolor: "#161b22", bordercolor: "#30363d", font: { color: "#c9d1d9" } },
  };
  Plotly.newPlot("plot", traces, layout, { responsive: true, displayModeBar: false });
}

function renderCards(data, colors) {
  const wrap = $("#cluster-cards");
  wrap.replaceChildren();
  for (const c of data.clusters) {
    const card = el("div", { class: "card" });
    card.style.borderLeftColor = colors[c.label];

    const h = el("h3");
    h.append(el("span", { class: "swatch" }));
    h.lastChild.style.background = colors[c.label];
    h.append(`${clusterName(c)} · ${c.size} papers`);
    card.append(h);

    const stats = el("div", { class: "stats" });
    stats.append(el("span", { html: `<b>${c.total_citations.toLocaleString()}</b> citations` }));
    stats.append(el("span", { html: `mean FWCI <b>${fmtFwci(c.mean_fwci)}</b>` }));
    stats.append(el("span", { html: `<b>${c.n_top_10_percent}</b> in top-10%` }));
    card.append(stats);

    const fields = (c.top_fields || []).map((f) => f[0]).slice(0, 2).join(", ");
    if (fields) card.append(el("div", { class: "muted", html: `<b style="color:var(--fg)">Fields:</b> ${fields}` }));

    if (c.description) card.append(el("div", { class: "desc" }, c.description));

    if (c.top_keywords?.length) {
      const kw = el("div", { class: "kw" });
      for (const [word] of c.top_keywords.slice(0, 5)) kw.append(el("span", {}, word));
      card.append(kw);
    }

    if (c.representative) {
      card.append(el("div", { class: "rep" }, `Representative: ${truncate(c.representative.title, 90)} (${c.representative.cited_by_count.toLocaleString()} cites)`));
    }
    wrap.append(card);
  }
}

async function loadExample(slug, tabEl) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  tabEl?.classList.add("active");
  $("#cluster-meta").textContent = "Loading…";
  try {
    const r = await fetch(`/api/examples/${slug}`);
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    const colors = clusterColors(data.clusters);
    $("#cluster-meta").innerHTML =
      `<b>${data.n_works}</b> papers · <b>${data.n_clusters}</b> clusters · query: <code>${data.query}</code>`;
    renderPlot(data, colors);
    renderCards(data, colors);
  } catch (e) {
    $("#cluster-meta").textContent = "Error loading example: " + e.message;
  }
}

async function initClusters() {
  try {
    const r = await fetch("/api/examples");
    const { examples } = await r.json();
    const tabs = $("#example-tabs");
    examples.forEach((ex, idx) => {
      const t = el("div", { class: "tab" + (idx === 0 ? " active" : ""), role: "button" }, ex.title);
      t.onclick = () => loadExample(ex.slug, t);
      tabs.append(t);
    });
    if (examples.length) loadExample(examples[0].slug, tabs.firstChild);
  } catch (e) {
    $("#cluster-meta").textContent = "Could not load examples.";
  }
}

// ---------------------------------------------------------------- boot
async function init() {
  try {
    const h = await (await fetch("/api/health")).json();
    if (h.max_results) $("#cap").textContent = h.max_results;
  } catch {}
  $("#search-form").addEventListener("submit", doSearch);
  doSearch();        // run the default query on load
  initClusters();
}
init();
