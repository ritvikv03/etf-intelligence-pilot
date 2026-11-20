"use strict";

const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="workspace-token"]').content;
const labels = {
  last_run: "Since last briefing", daily: "Daily", weekly: "Weekly", monthly: "Monthly",
  quarterly: "Quarterly", semiannually: "Semiannual", annually: "Annual",
  "3_year": "3 years", "5_year": "5 years", "10_year": "10 years", full_history: "Full archive", custom: "Custom",
};
const usdFormat = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });
let state;
let selectedReport;
let chartObserver;

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== null && text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function clear(container, ...children) {
  container.replaceChildren(...children);
}

function actionButton(text, click, style = "") {
  const button = el("button", text, "button " + style);
  button.type = "button";
  button.addEventListener("click", click);
  return button;
}

function safeLink(text, url, className = "") {
  try {
    const parsed = new URL(url, location.origin);
    if (!["http:", "https:"].includes(parsed.protocol)) return el("span", text);
    const link = el("a", text, className);
    link.href = parsed;
    if (parsed.origin !== location.origin || parsed.pathname === "/api/export") {
      link.target = "_blank";
      link.rel = "noopener";
    }
    return link;
  } catch {
    return el("span", text);
  }
}

function exportLink(id, kind, label, download = false) {
  const params = new URLSearchParams({ report: id, kind });
  if (download) params.set("download", "1");
  return safeLink(label, "/api/export?" + params, "button");
}

function badge(value, tone = "") {
  return el("span", value, "pill " + tone);
}

function message(text, error = false) {
  const node = $("message");
  node.textContent = text;
  node.classList.toggle("error", error);
  node.hidden = !text;
}

async function request(path, data) {
  const options = data === undefined ? undefined : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Workspace-Token": token },
    body: JSON.stringify(data),
  };
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "The workspace could not complete this request.");
  return body;
}

async function load(refresh = false) {
  const first = !state;
  state = await request("/api/state" + (selectedReport ? "?report=" + encodeURIComponent(selectedReport) : ""));
  if (first) controls();
  if (refresh || first) render();
}

async function submit(button, path, input) {
  button.disabled = true;
  message("");
  try {
    const result = await request(path, input);
    if (result.report_id) selectedReport = result.report_id;
    await load(true);
    message(result.message);
    return result;
  } catch (error) {
    message(error.message, true);
    return null;
  } finally {
    button.disabled = false;
  }
}

function view(name) {
  for (const section of document.querySelectorAll(".view")) section.hidden = section.id !== "view-" + name;
  for (const button of document.querySelectorAll("[data-view]")) {
    button.classList.toggle("active", button.dataset.view === name);
    if (button.dataset.view === name) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  if (name === "briefing") renderBriefing();
}

function setOptions(select, options, value) {
  clear(select, ...options.map(([key, label]) => {
    const option = el("option", label);
    option.value = key;
    return option;
  }));
  if (value !== undefined && options.some(([key]) => key === value)) select.value = value;
}

function check(value, label, checked = false) {
  const input = el("input");
  input.type = "checkbox";
  input.value = value;
  input.checked = checked;
  const node = el("label", null, "check");
  node.append(input, el("span", label));
  return node;
}

function checked(id) {
  return Array.from($(id).querySelectorAll("input:checked"), (input) => input.value);
}

function capital(value) {
  if (!value) return "";
  const plain = value.replace(/_/g, " ");
  return plain.charAt(0).toUpperCase() + plain.slice(1);
}

function tagLabel(tag) {
  const parent = state.catalog.find((item) => item.id === tag.parent_id);
  return (parent ? parent.label + " / " : "") + tag.label;
}

function controls() {
  setOptions($("lookback"), state.lookbacks.map((key) => [key, labels[key]]), "weekly");
  $("end-date").value = state.default_end;
  clear($("issuer-options"), ...state.issuers.map((issuer) => check(issuer, capital(issuer))));
  clear($("tag-options"), ...state.catalog.map((tag) => check(tag.id, tagLabel(tag))));
  clear($("pillar-options"), ...state.pillars.map((pillar) => check(pillar.id, pillar.label, true)));
  $("model-field").hidden = !state.model_enabled;
  $("lookback").addEventListener("change", () => {
    const custom = $("lookback").value === "custom";
    $("start-field").hidden = !custom;
    $("start-date").required = custom;
  });
  $("filters-panel").addEventListener("change", () => {
    const total = checked("issuer-options").length + checked("tag-options").length;
    $("filter-count").textContent = total ? total + " selected" : "All";
  });
}

function daterange(start, end) {
  if (!start || !end) return "";
  const format = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  return format.format(new Date(start + "T00:00:00Z")) + " – " + format.format(new Date(end + "T00:00:00Z"));
}

function summaryCard(name, value, meta, tone = "") {
  const card = el("div", null, "metric panel");
  card.append(el("span", name, "metric-name"), el("strong", value, "metric-value"),
              el("span", meta, "metric-meta " + tone));
  return card;
}

function panelHeading(title, description) {
  const header = el("div", null, "section-head");
  const left = el("div");
  left.append(el("h2", title));
  if (description) left.append(el("p", description));
  header.append(left);
  return header;
}

function table(title, description, headings, rows) {
  const panel = el("section", null, "panel table-panel");
  panel.append(panelHeading(title, description));
  if (!rows.length) {
    panel.append(el("p", "No matching records.", "empty"));
    return panel;
  }
  const wrap = el("div", null, "table-wrap");
  const grid = el("table");
  const header = el("tr");
  for (const heading of headings) header.append(el("th", heading));
  const head = el("thead");
  head.append(header);
  const body = el("tbody");
  for (const row of rows) {
    const line = el("tr");
    for (const value of row) {
      const cell = el("td");
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value ?? "—";
      line.append(cell);
    }
    body.append(line);
  }
  grid.append(head, body);
  wrap.append(grid);
  panel.append(wrap);
  return panel;
}

function drawChart(canvas, baseline, current, currency) {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const max = Math.max(baseline, current, 1);
  const step = Math.pow(10, Math.floor(Math.log10(max / 4)));
  const ceiling = Math.ceil(max / (step * 4)) * step * 4;
  const left = 55, right = width - 10, top = 15, bottom = height - 24;
  const colors = ["#bcd9cd", "#1c765f"];
  ctx.font = "10px system-ui";
  ctx.textAlign = "right";
  for (let n = 0; n <= 4; n++) {
    const y = bottom - (bottom - top) * n / 4;
    ctx.strokeStyle = "#eaf0ed";
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
    ctx.fillStyle = "#627476";
    ctx.fillText(usdFormat.format(ceiling * n / 4), left - 8, y + 4);
  }
  ctx.textAlign = "center";
  ctx.fillStyle = "#627476";
  ctx.fillText(currency, 22, top - 4);
  [baseline, current].forEach((value, i) => {
    const x = left + (right - left) * (i ? .71 : .29);
    const h = (bottom - top) * value / ceiling;
    const w = Math.max(18, Math.min(92, (right - left) / 4));
    ctx.fillStyle = colors[i];
    ctx.beginPath();
    ctx.roundRect(x - w / 2, bottom - h, w, h, [5, 5, 0, 0]);
    ctx.fill();
    ctx.fillStyle = "#29453e";
    ctx.font = "600 11px system-ui";
    ctx.fillText(usdFormat.format(value), x, Math.max(top, bottom - h - 6));
    ctx.font = "10px system-ui";
    ctx.fillText(i ? "Current" : "Baseline", x, height - 5);
  });
}

function trendPanel(report) {
  const panel = el("section", null, "panel");
  panel.append(panelHeading("Matched-cohort net assets",
    report.matched.n + " of " + report.matched.of + " current products with comparable observations"));
  const frame = el("div", null, "chart-frame");
  if (report.matched.state !== "available" || !report.chart) {
    frame.append(el("p", "Both asset measurements are needed for a matched comparison.", "empty"));
  } else {
    const canvas = el("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", report.matched.baseline + " baseline and " + report.matched.current + " current");
    frame.append(canvas);
    const legend = el("div", null, "chart-legend");
    for (const value of ["Baseline " + report.matched.baseline_asof, "Current " + report.matched.current_asof]) {
      const block = el("span");
      block.append(el("i"), document.createTextNode(value));
      legend.append(block);
    }
    frame.append(legend);
    chartObserver = new ResizeObserver(() => drawChart(canvas, Number(report.chart.baseline), Number(report.chart.current), report.currency));
    chartObserver.observe(canvas);
  }
  panel.append(frame);
  return panel;
}

function citations(ids, records) {
  const links = el("div", null, "citations");
  for (const id of ids) {
    const row = records.get(id);
    if (row) {
      const link = row.url ? safeLink(id, row.url) : el("span", id);
      link.title = row.title;
      links.append(link);
    }
  }
  return links;
}

function synopsis(report, records) {
  const panel = el("section", null, "panel");
  const synthesis = report.synthesis;
  panel.append(panelHeading("Evidence highlights", synthesis?.notice ||
    (synthesis?.method === "local_model" ? "Local model analysis for review" : "From the archived source records")));
  const list = el("ul", null, "evidence-list");
  for (const item of synthesis?.items ?? []) {
    const row = el("li");
    row.append(el("span", capital(item.pillar), "eyebrow"), el("span", item.text), citations(item.evidence_ids, records));
    list.append(row);
  }
  if (!list.childElementCount) list.append(el("li", "No matching archived commentary."));
  panel.append(list);
  return panel;
}

function archiveBlock(label, content) {
  const detail = el("details", null, "panel archive");
  detail.append(el("summary", label), content);
  return detail;
}

function renderBriefing() {
  if (chartObserver) chartObserver.disconnect();
  const report = state.report;
  const content = $("briefing-content");
  const actions = $("briefing-actions");
  clear(actions);
  if (!report) {
    $("briefing-date").textContent = "Choose a lookback and run a briefing.";
    clear(content, el("div", "No briefings have been generated for this client.", "panel empty"));
    return;
  }
  const record = state.reports.find((row) => row.report_id === report.report_id);
  $("briefing-date").textContent = daterange(report.window.start, report.window.current) + " · " + (labels[report.lookback] || report.lookback);
  actions.append(badge(capital(report.status), report.status === "draft" ? "warn" : ""));
  if (record?.exportable) actions.append(exportLink(report.report_id, "html", "Open HTML"));
  const pillars = new Set(report.pillars.map((pillar) => pillar.id));
  const assetsShown = pillars.has("assets_growth");
  const feesShown = pillars.has("pricing_economics");
  const metrics = el("div", null, "metrics");
  if (pillars.has("product_activity")) {
    metrics.append(summaryCard("Active products", report.counts.current, report.counts.change + " vs. baseline"));
  }
  if (assetsShown) metrics.append(
    summaryCard("Tracked fund net assets", report.snapshot_current.text, report.snapshot_current.cov + " current products covered"),
    summaryCard("Matched-cohort change", report.matched.pct, report.matched.change,
      report.matched.pct.startsWith("+") ? "good" : "")
  );
  if (feesShown) metrics.append(summaryCard("Asset-weighted " + report.fee_label, report.weighted.current || "Unavailable",
    report.weighted.change ? report.weighted.change + " vs. baseline" : "Compatible fee data required"));
  const records = new Map(report.register.map((record) => [record.id, record]));
  const summaryGrid = el("div", null, "briefing-grid" + (assetsShown ? "" : " single"));
  if (assetsShown) summaryGrid.append(trendPanel(report));
  summaryGrid.append(synopsis(report, records));
  const fee = new Map(report.fees.map((line) => [line.ticker, line]));
  const assetTable = table("Products and fees", "Tracked products and eligible observations in this briefing",
    ["Product", ...(assetsShown ? ["Baseline assets", "Current assets", "Asset change"] : []),
      ...(feesShown ? ["Current fee", "Fee change"] : [])],
    report.assets.map((a) => {
      const name = el("div");
      name.append(el("strong", a.ticker), el("small", a.name));
      return [name, ...(assetsShown ? [a.baseline, a.current, a.pct] : []),
        ...(feesShown ? [fee.get(a.ticker)?.current, fee.get(a.ticker)?.change] : [])];
    })
  );
  const revenue = report.revenue;
  const economics = table("Revenue coverage", "Reported revenue uses exact periods. Expense proxies use net assets and net fees.",
    ["Measure", "Current", "Change"], [
      ["Reported product revenue", revenue?.current ?? "Unavailable", revenue?.change ?? "Unavailable"],
      ["Annualized expense proxy", report.proxy.current ?? "Unavailable", report.proxy.change ?? "Unavailable"],
    ]);
  const coverage = el("ul");
  for (const item of report.limitations) coverage.append(el("li", item));
  const register = table("Evidence register", "", ["Source record", "Source", "Date", "Notes"], report.register.map((row) =>
    [row.url ? safeLink(row.title, row.url) : row.title, row.source, row.date, row.note]));
  const panels = [...(metrics.childElementCount ? [metrics] : []), summaryGrid];
  if (assetsShown || feesShown) panels.push(assetTable);
  if (feesShown) panels.push(economics);
  clear(content, ...panels, archiveBlock("Coverage notes", coverage), archiveBlock("Browse all evidence", register));
}

function renderSources() {
  clear($("source-content"), table("Source registry", "Edit source permissions and endpoints in the client YAML.",
    ["Source", "Purpose", "Access", "Latest CSV import", "RSS collection"], state.sources.map((source) => {
      const name = el("div");
      name.append(el("strong", source.source_id), el("small", source.owner || "Unassigned owner"));
      if (source.endpoint) name.append(safeLink("Source endpoint ↗", source.endpoint));
      const access = el("div");
      access.append(badge(source.enabled ? "Enabled" : "Disabled", source.enabled ? "" : "neutral"));
      if (source.permission) access.append(el("small", capital(source.permission)));
      const history = el("div");
      history.append(el("span", capital(source.status)));
      if (source.finished_at) history.append(el("small",
        source.inserted + " inserted · " + source.skipped + " skipped · " + source.rejected + " rejected"));
      const collection = el("div");
      collection.append(el("span", source.feed ? capital(source.feed.status) : "Unrecorded"));
      if (source.feed?.detail) collection.append(el("small", source.feed.detail));
      return [name, capital(source.purpose), access, history, collection];
    })
  ));
  setOptions($("import-source"), [["", "Unspecified"], ...state.sources
    .filter((source) => source.enabled && source.purpose === "product_identity")
    .map((source) => [source.source_id, source.source_id])], $("import-source").value);
}

function reviewCard(event) {
  const panel = el("article", null, "panel review-card");
  panel.append(badge(capital(event.review_status), "warn"), el("h3", event.title));
  panel.append(el("p", (event.published_at || "Publication date unavailable") + " · " + capital(event.event_type), "muted"));
  if (event.url) panel.append(safeLink("Open source evidence", event.url));
  const controls = el("div", null, "review-controls");
  const candidates = event.choices.length ? event.choices : state.products.filter((p) => p.review_status === "approved").map((p) => p.fund_id);
  const select = el("select");
  setOptions(select, [["", "Choose a product"], ...candidates.map((id) => {
    const product = state.products.find((p) => p.fund_id === id);
    return [id, product ? product.ticker + " · " + product.listing_venue : id];
  })], event.choices.length === 1 ? event.choices[0] : "");
  const label = el("label", "Resolved product");
  label.append(select);
  controls.append(label);
  for (const decision of ["accept", "defer", "reject"]) {
    const button = actionButton(capital(decision), () => submit(button, "/api/review", {
      reviewer: $("reviewer").value, event_id: event.event_id, decision, fund_id: select.value || null,
    }), decision === "accept" ? "primary" : "");
    controls.append(button);
  }
  panel.append(controls);
  return panel;
}

function renderTagOptions() {
  const product = state.products.find((p) => p.fund_id === $("tag-product").value);
  const tags = new Set(product?.tag_ids ?? []);
  const identifiers = Object.entries(product?.identifiers ?? {}).map(([kind, values]) => capital(kind) + " " + values.join(", "));
  const history = (product?.listing_history ?? []).map((listing) =>
    [listing.ticker, listing.venue, "changed " + listing.at.slice(0, 10)].filter(Boolean).join(" "));
  $("tag-provenance").textContent = [
    product?.listing_venue, ...identifiers, ...(history.length ? ["Prior listings " + history.join(", ")] : []),
  ].filter(Boolean).join(" · ");
  const suggestions = state.report?.synthesis?.tag_suggestions?.filter((item) => item.fund_id === product?.fund_id) ?? [];
  const suggested = new Set(suggestions.map((item) => item.tag_id));
  clear($("edit-tags"), ...state.catalog.map((tag) => check(tag.id,
    tagLabel(tag) + (suggested.has(tag.id) ? " · suggested" : ""), tags.has(tag.id))));
}

function renderReview() {
  clear($("review-content"), ...state.pending.map(reviewCard));
  if (!state.pending.length) $("review-content").append(el("div", "The review queue is clear.", "panel empty"));
  setOptions($("tag-product"), state.products.map((product) => [
    product.fund_id, product.ticker + " · " + product.name + (product.reviewer ? " (reviewed)" : ""),
  ]), $("tag-product").value);
  $("tags-form").hidden = !state.products.length || !state.catalog.length;
  renderTagOptions();
}

function renderLibrary() {
  clear($("library-content"), table("Saved briefings", "Reviewed and finalized copies retain their saved evidence and content.",
    ["Window", "Profile", "State", "Actions"], state.reports.map((row) => {
      const actions = el("div", null, "actions");
      actions.append(actionButton("Open briefing", async () => {
        selectedReport = row.report_id;
        try {
          await load(true);
          view("briefing");
        } catch (error) { message(error.message, true); }
      }));
      if (row.exportable) {
        actions.append(exportLink(row.report_id, "html", "HTML"), exportLink(row.report_id, "manifest", "Manifest", true));
        if (row.status !== "finalized") {
          const status = row.status === "draft" ? "reviewed" : "finalized";
          const button = actionButton(status === "reviewed" ? "Mark reviewed" : "Finalize",
            () => submit(button, "/api/status", { report_id: row.report_id, reviewer: $("library-reviewer").value, status }),
            "primary");
          actions.append(button);
        }
      }
      return [daterange(row.window_start, row.window_end) + " (end exclusive)", capital(row.profile),
        badge(capital(row.status), row.status === "draft" ? "warn" : ""), actions];
    })
  ));
}

function render() {
  $("client-name").textContent = state.client;
  $("mode-badge").textContent = state.mode === "demo" ? "Synthetic demo" : "Local pilot";
  $("mode-badge").classList.toggle("warn", state.mode === "demo");
  $("workspace-mode").textContent = state.mode === "demo" ? "Demo data" : "Local pilot";
  $("workspace-timezone").textContent = state.timezone;
  $("queue-count").textContent = state.pending.length || "";
  renderBriefing();
  renderSources();
  renderReview();
  renderLibrary();
}

for (const button of document.querySelectorAll("[data-view]")) {
  button.addEventListener("click", () => view(button.dataset.view));
}
$("briefing-form").addEventListener("submit", (event) => {
  event.preventDefault();
  $("filters-panel").open = false;
  const lookback = $("lookback").value;
  const pillars = checked("pillar-options");
  if (!pillars.length && state.pillars.length) {
    message("Select at least one report pillar.", true);
    return;
  }
  submit(event.submitter, "/api/report", {
    lookback, end: $("end-date").value, start: lookback === "custom" ? $("start-date").value : null,
    issuer_ids: checked("issuer-options"), tag_ids: checked("tag-options"),
    pillar_ids: pillars.length === state.pillars.length ? [] : pillars, request_model: $("model-checkbox").checked,
  });
});
$("collect-button").addEventListener("click", (event) => submit(event.currentTarget, "/api/collect", {}));
$("import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("import-file").files[0];
  if (!file || file.size > 1024 * 1024) {
    message("Choose a CSV file under 1 MiB.", true);
    return;
  }
  try {
    const result = await submit(event.submitter, "/api/import", {
      filename: file.name, content: await file.text(), kind: $("import-kind").value,
      source_id: $("import-source").value || null,
    });
    if (result) clear($("import-errors"), ...result.errors.map((error) => el("li", "Row " + error.row + " · " + error.message)));
  } catch (error) { message(error.message, true); }
});
$("tag-product").addEventListener("change", renderTagOptions);
$("tags-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(event.submitter, "/api/tags", {
    reviewer: $("reviewer").value, fund_id: $("tag-product").value, tag_ids: checked("edit-tags"),
  });
});
load().catch((error) => message(error.message, true));
