(function () {
  "use strict";

  const boot = JSON.parse(document.getElementById("bootstrap-data").textContent);
  let csrfToken = boot.csrf_token;
  let currentReport = null;
  let previousReport = null;
  let activeRunId = null;
  let pollTimer = null;
  let runStartedAt = null;
  let planTimer = null;
  let planSeq = 0;
  let busyPollTimer = null;

  const el = (id) => document.getElementById(id);

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function textNodePre(text) {
    const pre = document.createElement("pre");
    pre.textContent = text == null ? "" : String(text);
    return pre;
  }

  function verdictHeadline(v) {
    if (v === "PASS") return "Consistent on tested cases";
    if (v === "INCONCLUSIVE") return "Inconclusive — incomplete or insufficient verification";
    if (v === "FAIL") return "Issues found — builds or behavior differ";
    return String(v || "No result");
  }

  function verdictClass(v) {
    if (v === "PASS") return "verdict-banner--pass";
    if (v === "INCONCLUSIVE") return "verdict-banner--inconclusive";
    return "verdict-banner--fail";
  }

  function collectPayload() {
    const mode = document.querySelector('.mode-tab[aria-selected="true"]').dataset.mode;
    const toolchains = [...document.querySelectorAll('input[name="toolchain"]:checked')].map(
      (c) => c.value
    );
    const optimizations = [...document.querySelectorAll('input[name="optimization"]:checked')].map(
      (c) => c.value
    );
    const base = {
      mode,
      csrf_token: csrfToken,
      toolchains,
      optimizations,
      enable_ubsan: el("enable-ubsan").checked,
    };
    if (mode === "example") {
      base.suite_id = el("example-select").value;
    } else if (mode === "custom") {
      base.source_text = el("custom-source").value;
      base.stdin_text = el("custom-stdin").value;
    } else if (mode === "generated") {
      base.program_id = el("generated-program").value;
      base.seed = parseInt(el("generated-seed").value, 10) || 0;
      base.case_count = parseInt(el("generated-count").value, 10) || 4;
    }
    return base;
  }

  function scheduleRefreshPlan() {
    if (planTimer) clearTimeout(planTimer);
    planTimer = setTimeout(refreshPlan, 280);
  }

  async function refreshPlan() {
    const payload = collectPayload();
    delete payload.csrf_token;
    const seq = ++planSeq;
    try {
      const res = await fetch("/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json", Origin: window.location.origin },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (seq !== planSeq) return;
      if (data.error) {
        el("run-plan").innerHTML = `<p class="field-hint">${escapeHtml(data.error)}</p>`;
        return;
      }
      el("run-plan").innerHTML = `
        <strong>${escapeHtml(data.title)}</strong>
        <p>${escapeHtml(data.detail)}</p>
        <p class="matrix-preview">${escapeHtml(data.matrix_label)}</p>`;
      el("matrix-label").textContent = data.matrix_label;
    } catch (_) {
      if (seq !== planSeq) return;
      el("run-plan").innerHTML = `<p class="field-hint">Could not compute run plan.</p>`;
    }
  }

  function renderToolchains() {
    const container = el("toolchain-options");
    container.innerHTML = "";
    if (!boot.toolchains.length) {
      container.innerHTML = '<p class="field-hint">No C++17 toolchain passed smoke probe on this host.</p>';
      el("run-btn").disabled = true;
      return;
    }
    boot.toolchains.forEach((tc) => {
      const id = `tc-${tc.id}`;
      const label = document.createElement("label");
      label.className = "toolchain-option";
      label.innerHTML = `<input type="checkbox" name="toolchain" value="${escapeHtml(tc.id)}" id="${id}" checked>
        <span><strong>${escapeHtml(tc.id)}</strong><span class="toolchain-option__meta">${escapeHtml(tc.version_line)}</span></span>`;
      container.appendChild(label);
    });
  }

  function renderExamples() {
    const sel = el("example-select");
    sel.innerHTML = "";
    Object.entries(boot.examples).forEach(([id, meta]) => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = meta.label;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", () => loadExampleSource());
  }

  async function loadExampleSource() {
    const sid = el("example-select").value;
    const ta = el("example-source-preview");
    try {
      const res = await fetch(`/api/example/${encodeURIComponent(sid)}/source`);
      const data = await res.json();
      ta.value = data.source_text || "";
    } catch (_) {
      ta.value = "";
    }
    refreshPlan();
  }

  function renderGeneratedPrograms() {
    const sel = el("generated-program");
    sel.innerHTML = "";
    Object.entries(boot.generated_programs).forEach(([id, meta]) => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = meta.label;
      sel.appendChild(opt);
    });
  }

  function renderUbsan() {
    const list = el("ubsan-list");
    if (!boot.ubsan_status.length) {
      list.textContent = "No toolchain probes yet.";
      return;
    }
    list.innerHTML = boot.ubsan_status
      .map((u) => {
        const state = u.supported ? "Available" : "Unavailable on this host";
        const detail = u.summary || u.message || "";
        return `<li><strong>${escapeHtml(u.toolchain_id)}</strong>: ${escapeHtml(state)}${
          detail ? `<span class="ubsan-detail">${escapeHtml(detail)}</span>` : ""
        }</li>`;
      })
      .join("");
  }

  function renderHeaderChips() {
    const wrap = el("toolchain-chips");
    wrap.innerHTML = "";
    if (!boot.toolchains.length) {
      wrap.innerHTML = '<span class="chip chip--bad"><span class="dot"></span>No C++17 toolchain</span>';
      return;
    }
    boot.toolchains.forEach((tc) => {
      const span = document.createElement("span");
      span.className = "chip chip--ok";
      span.innerHTML = `<span class="dot"></span>${escapeHtml(tc.id)} ready`;
      wrap.appendChild(span);
    });
    const ubsanAny = boot.ubsan_status.some((u) => u.supported);
    const u = document.createElement("span");
    u.className = ubsanAny ? "chip chip--ok" : "chip chip--warn";
    u.innerHTML = `<span class="dot"></span>UBSan ${ubsanAny ? "available" : "limited"}`;
    wrap.appendChild(u);
  }

  function issueCounts(report) {
    const issues = (report.interpretation && report.interpretation.issues) || [];
    const behavior = issues.filter((i) =>
      /mismatch|oracle_disagreement|wrong_output/i.test(i.flag)
    ).length;
    const exec = issues.filter((i) =>
      /compile|timeout|spawn|truncated|runtime|internal|deadline|empty_suite/i.test(i.flag)
    ).length;
    return { behavior, exec, total: issues.length };
  }

  function profileSourceKey(p) {
    return String(p.source_path || "");
  }

  function countSourceCasePairs(report) {
    const release = (report.profiles || []).filter(
      (p) => (p.compiler_config || p.config)?.build_kind === "release"
    );
    const bySrc = new Map();
    release.forEach((p) => {
      const key = profileSourceKey(p);
      const runs = p.observations?.runs || p.runs || [];
      if (!bySrc.has(key)) bySrc.set(key, runs.length);
    });
    let total = 0;
    bySrc.forEach((n) => {
      total += n;
    });
    return { sources: bySrc.size, pairs: total };
  }

  function countConfigsFullyExecuted(report) {
    let done = 0;
    (report.profiles || []).forEach((p) => {
      const cfg = p.compiler_config || p.config || {};
      if (cfg.build_kind === "ubsan_diagnostic") return;
      const comp = p.observations?.compile || p.compile || {};
      if (comp.status !== "ok") return;
      const runs = p.observations?.runs || p.runs || [];
      const okRuns = runs.filter((r) => !r.skipped && r.status === "ok").length;
      if (runs.length && okRuns === runs.length) done += 1;
    });
    return done;
  }

  function countReleaseProfiles(report) {
    return (report.profiles || []).filter(
      (p) => (p.compiler_config || p.config)?.build_kind === "release"
    ).length;
  }

  function requestedConfigTotal(report) {
    const req = report.requested_release_by_source || {};
    return Object.values(req).reduce((a, b) => a + b, 0);
  }

  function sumDurations(report) {
    let sec = 0;
    (report.profiles || []).forEach((p) => {
      const obs = p.observations || {};
      const comp = obs.compile || p.compile;
      if (comp && comp.duration_sec) sec += comp.duration_sec;
      const runs = obs.runs || p.runs || [];
      runs.forEach((r) => {
        if (r.duration_sec) sec += r.duration_sec;
      });
    });
    return sec;
  }

  function renderSummary(report, container) {
    const ic = issueCounts(report);
    const interp = report.interpretation || {};
    const elapsed =
      report._dashboard_elapsed_sec != null
        ? report._dashboard_elapsed_sec
        : sumDurations(report).toFixed(2);

    const sc = countSourceCasePairs(report);
    container.innerHTML = `
      <div class="summary-grid">
        <div class="stat-card"><div class="value">${countConfigsFullyExecuted(report)}/${requestedConfigTotal(report) || countReleaseProfiles(report)}</div><div class="label">Configurations fully executed / requested</div></div>
        <div class="stat-card"><div class="value">${sc.sources} · ${sc.pairs}</div><div class="label">Sources · source-case pairs (release)</div></div>
        <div class="stat-card"><div class="value">${ic.behavior}</div><div class="label">Behavioral differences</div></div>
        <div class="stat-card"><div class="value">${ic.exec}</div><div class="label">Execution / build issues</div></div>
        <div class="stat-card"><div class="value">${elapsed}s</div><div class="label">Elapsed time</div></div>
      </div>`;
  }

  function renderVerdict(report, container) {
    const interp = report.interpretation || {};
    const v = interp.overall_verdict;
    const cls = verdictClass(v);
    const unful = interp.unfulfilled_requested_configurations || [];
    let warnings = "";
    if (unful.length) {
      warnings += `<ul class="alert-list">${unful
        .map((u) => `<li>Missing config: ${escapeHtml(u.toolchain)} ${escapeHtml(u.optimization || "")} — ${escapeHtml(u.reason)}</li>`)
        .join("")}</ul>`;
    }
    if (interp.coverage === "PARTIAL" && v !== "PASS") {
      warnings += `<p class="field-hint">Executed coverage is partial — not all planned configurations or cases finished successfully.</p>`;
    }
    container.innerHTML = `
      <div class="verdict-banner ${cls}" role="status">
        <h2>${escapeHtml(verdictHeadline(v))}</h2>
        <p>${escapeHtml(interp.pass_meaning || "")}</p>
        <div class="badges">
          <span class="badge">Verdict: ${escapeHtml(v)}</span>
          <span class="badge">Executed: ${escapeHtml(interp.coverage)}</span>
          <span class="badge ${interp.requested_coverage === "PARTIAL" ? "badge--warn" : ""}">Requested: ${escapeHtml(interp.requested_coverage)}</span>
        </div>
        ${warnings}
      </div>`;
  }

  function profileRows(report) {
    return (report.profiles || []).map((p, idx) => {
      const cfg = p.compiler_config || {};
      const obs = p.observations || {};
      const comp = obs.compile || p.compile || {};
      const runs = obs.runs || p.runs || [];
      const completed = runs.filter((r) => !r.skipped && r.status === "ok").length;
      const outcome = comp.status !== "ok" ? comp.status : runs.some((r) => r.status !== "ok") ? "mixed" : "ok";
      let dur = comp.duration_sec || 0;
      runs.forEach((r) => {
        if (r.duration_sec) dur += r.duration_sec;
      });
      const srcKey = profileSourceKey(p);
      const srcLabel = srcKey.split(/[/\\]/).pop() || srcKey;
      return { idx, p, cfg, comp, runs, completed, outcome, dur, srcKey, srcLabel };
    });
  }

  function renderConfigTable(report, tbody) {
    tbody.innerHTML = "";
    profileRows(report).forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(row.srcLabel)}</td>
        <td>${escapeHtml(row.cfg.version_line || row.cfg.toolchain_id || "")}</td>
        <td>${escapeHtml(row.cfg.optimization || "")}</td>
        <td>${escapeHtml(row.cfg.build_kind || "release")}</td>
        <td>${row.completed}/${row.runs.length}</td>
        <td>${escapeHtml(row.outcome)}</td>
        <td>${row.dur ? row.dur.toFixed(3) + "s" : "—"}</td>
        <td><button type="button" class="row-toggle" data-idx="${row.idx}">Details</button></td>`;
      tbody.appendChild(tr);

      const detailTr = document.createElement("tr");
      detailTr.hidden = true;
      detailTr.dataset.detailFor = String(row.idx);
      const td = document.createElement("td");
      td.colSpan = 8;
      td.className = "detail-panel";
      td.appendChild(buildCaseDetails(report, row));
      detailTr.appendChild(td);
      tbody.appendChild(detailTr);
    });

    tbody.querySelectorAll(".row-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = btn.dataset.idx;
        const detailRow = tbody.querySelector(`tr[data-detail-for="${idx}"]`);
        const open = detailRow.hidden;
        detailRow.hidden = !open;
        btn.textContent = open ? "Hide" : "Details";
      });
    });
  }

  function buildCaseDetails(report, row) {
    const wrap = document.createElement("div");
    const caseNames = [...new Set(row.runs.map((r) => r.case_name))];
    const sel = document.createElement("select");
    sel.setAttribute("aria-label", "Select case");
    caseNames.forEach((cn) => {
      const o = document.createElement("option");
      o.value = cn;
      o.textContent = cn;
      sel.appendChild(o);
    });
    wrap.appendChild(sel);

    const tabs = document.createElement("div");
    tabs.className = "tabs";
    ["outputs", "build", "ubsan", "repro"].forEach((t, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "tab";
      b.dataset.tab = t;
      b.textContent = { outputs: "Outputs & comparison", build: "Build logs", ubsan: "UBSan", repro: "Reproduction" }[t];
      b.setAttribute("aria-selected", i === 0 ? "true" : "false");
      tabs.appendChild(b);
    });
    wrap.appendChild(tabs);

    const panels = document.createElement("div");
    panels.className = "tab-panels";
    wrap.appendChild(panels);

    function renderPanels(caseName) {
      panels.innerHTML = "";
      const outputs = document.createElement("div");
      outputs.className = "tab-panel";
      outputs.dataset.panel = "outputs";
      outputs.appendChild(renderCompareGrid(report, row.srcKey, caseName));

      const build = document.createElement("div");
      build.className = "tab-panel";
      build.hidden = true;
      build.dataset.panel = "build";
      build.appendChild(textNodePre(formatBuildLog(row)));

      const ubsan = document.createElement("div");
      ubsan.className = "tab-panel";
      ubsan.hidden = true;
      ubsan.dataset.panel = "ubsan";
      ubsan.appendChild(renderUbsanTab(report));

      const repro = document.createElement("div");
      repro.className = "tab-panel";
      repro.hidden = true;
      repro.dataset.panel = "repro";
      repro.appendChild(textNodePre(extractRepro(report, row.idx)));

      panels.append(outputs, build, ubsan, repro);

      tabs.querySelectorAll(".tab").forEach((tab) => {
        tab.addEventListener("click", () => {
          tabs.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", "false"));
          tab.setAttribute("aria-selected", "true");
          panels.querySelectorAll(".tab-panel").forEach((p) => {
            p.hidden = p.dataset.panel !== tab.dataset.tab;
          });
        });
      });
    }

    sel.addEventListener("change", () => renderPanels(sel.value));
    renderPanels(caseNames[0] || "");
    return wrap;
  }

  function streamDisplay(stream) {
    if (!stream) return "";
    if (typeof stream === "string") return stream;
    return stream.display_text != null ? stream.display_text : "";
  }

  function normalizedStreamKey(stream) {
    if (!stream || typeof stream === "string" || !stream.bytes_base64) return null;
    const bin = Uint8Array.from(atob(stream.bytes_base64), (c) => c.charCodeAt(0));
    const parts = [];
    for (let i = 0; i < bin.length; i++) {
      if (bin[i] === 13 && i + 1 < bin.length && bin[i + 1] === 10) {
        parts.push("\n");
        i += 1;
      } else {
        parts.push(String.fromCharCode(bin[i]));
      }
    }
    return parts.join("");
  }

  function renderCompareGrid(report, sourceKey, caseName) {
    const grid = document.createElement("div");
    grid.className = "compare-grid";
    const entries = [];
    (report.profiles || []).forEach((p) => {
      if (profileSourceKey(p) !== sourceKey) return;
      const cfg = p.compiler_config || {};
      if (cfg.build_kind === "ubsan_diagnostic") return;
      const runs = p.observations?.runs || p.runs || [];
      const matching = runs.filter((r) => r.case_name === caseName);
      if (matching.length !== 1) return;
      const run = matching[0];
      if (run.skipped || run.stdout?.truncated || run.stdout_truncated) return;
      entries.push({ label: `${cfg.toolchain_id} ${cfg.optimization}`, run });
    });
    const normKeys = entries.map((e) => normalizedStreamKey(e.run.stdout));
    const refKey = normKeys.length ? normKeys[0] : null;
    entries.forEach((e, i) => {
      const block = document.createElement("div");
      const diff = refKey != null && normKeys[i] != null && normKeys[i] !== refKey;
      block.className = "output-block" + (diff ? " diff" : "");
      block.innerHTML = `<strong>${escapeHtml(e.label)}</strong>
        <p class="field-hint">exit=${escapeHtml(String(e.run.exit_code))} · truncated=${e.run.stdout?.truncated || e.run.stdout_truncated ? "yes" : "no"}</p>`;
      block.appendChild(textNodePre(streamDisplay(e.run.stdout)));
      const err = streamDisplay(e.run.stderr);
      if (err) {
        const se = document.createElement("p");
        se.className = "field-hint";
        se.textContent = "stderr:";
        block.appendChild(se);
        block.appendChild(textNodePre(err));
      }
      const stdin = e.run.stdin != null ? e.run.stdin : "";
      block.appendChild(textNodePre("stdin:\n" + stdin));
      grid.appendChild(block);
    });
    if (!entries.length) {
      grid.innerHTML = '<p class="field-hint">No comparable runs for this case.</p>';
    }
    return grid;
  }

  function formatBuildLog(row) {
    const c = row.comp;
    const out = streamDisplay(c.stdout);
    const err = streamDisplay(c.stderr);
    return `status: ${c.status}\ncommand: ${(c.command_argv || c.command || []).join(" ")}\n--- stdout ---\n${out}\n--- stderr ---\n${err}`;
  }

  function renderUbsanTab(report) {
    const div = document.createElement("div");
    const diag = report.diagnostics || {};
    const probes = diag.ubsan_probe || [];
    const findings = diag.ubsan_findings || [];
    div.innerHTML = `<p>${escapeHtml(diag.ubsan_notes || "")}</p>`;
    const ul = document.createElement("ul");
    probes.forEach((p) => {
      const li = document.createElement("li");
      li.innerHTML = `<strong>${escapeHtml(p.toolchain_id)}</strong>: ${p.supported ? "supported" : "unsupported"}`;
      ul.appendChild(li);
    });
    div.appendChild(ul);
    if (findings.length) {
      const det = document.createElement("details");
      det.innerHTML = "<summary>View UBSan findings</summary>";
      det.appendChild(textNodePre(JSON.stringify(findings, null, 2)));
      div.appendChild(det);
    }
    probes.forEach((p) => {
      if (!p.supported && p.message) {
        const det = document.createElement("details");
        det.innerHTML = "<summary>Full linker diagnostic</summary>";
        det.appendChild(textNodePre(p.message));
        div.appendChild(det);
      }
    });
    return div;
  }

  function extractRepro(report, profileIdx) {
    const meta = report._meta || {};
    const scripts = meta.reproduction?.powershell_scripts || [];
    const entry = scripts.find((s) => s.profile_index === profileIdx);
    if (entry) return entry.script;
    return meta.reproduction_powershell_text || "(No reproduction script for this profile.)";
  }

  function renderFullResults(report, targetEl, isPrevious) {
    targetEl.hidden = false;
    targetEl.classList.toggle("is-previous", !!isPrevious);
    const summaryHost = targetEl.querySelector(".js-summary");
    const verdictHost = targetEl.querySelector(".js-verdict");
    const tbody = targetEl.querySelector(".js-config-body");
    renderSummary(report, summaryHost);
    renderVerdict(report, verdictHost);
    renderConfigTable(report, tbody);
    const runId = report.run_id;
    targetEl.querySelector(".js-dl-json").href = `/download/${encodeURIComponent(runId)}/report.json`;
    targetEl.querySelector(".js-dl-txt").href = `/download/${encodeURIComponent(runId)}/report.txt`;
  }

  function showRunning(show) {
    const box = el("run-status");
    box.hidden = !show;
    box.classList.toggle("run-status--active", show);
    el("run-btn").disabled = show || !boot.toolchains.length;
  }

  function updateElapsed() {
    if (!runStartedAt) return;
    const sec = ((Date.now() - runStartedAt) / 1000).toFixed(1);
    el("run-status-text").textContent = `Verification running… ${sec}s elapsed`;
  }

  async function pollRun(runId) {
    try {
      const res = await fetch(`/api/run/${encodeURIComponent(runId)}/status`);
      const data = await res.json();
      if (data.status === "running") {
        el("run-status-text").textContent = `Verification running… ${data.elapsed_sec}s elapsed`;
        return;
      }
      clearInterval(pollTimer);
      pollTimer = null;
      showRunning(false);
      activeRunId = null;

      if (data.status === "error") {
        el("run-error").hidden = false;
        el("run-error").textContent = data.error || "Run failed.";
        return;
      }
      if (data.report) {
        el("run-error").hidden = true;
        if (currentReport) {
          previousReport = currentReport;
          renderFullResults(previousReport, el("results-previous"), true);
        }
        data.report._dashboard_elapsed_sec = data.elapsed_sec;
        currentReport = data.report;
        renderFullResults(currentReport, el("results-current"), false);
        el("results-empty").style.display = "none";
      }
    } catch (_) {
      clearInterval(pollTimer);
      showRunning(false);
      el("run-error").hidden = false;
      el("run-error").textContent = "Lost connection to the dashboard backend.";
    }
  }

  async function startRun() {
    el("run-error").hidden = true;
    const payload = collectPayload();
    showRunning(true);
    runStartedAt = Date.now();
    updateElapsed();
    try {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json", Origin: window.location.origin },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        showRunning(false);
        el("run-error").hidden = false;
        el("run-error").textContent = data.error || "Could not start run.";
        if (data.csrf_token) csrfToken = data.csrf_token;
        return;
      }
      csrfToken = data.csrf_token || csrfToken;
      activeRunId = data.run_id;
      pollTimer = setInterval(() => pollRun(activeRunId), 500);
      pollRun(activeRunId);
    } catch (_) {
      showRunning(false);
      el("run-error").hidden = false;
      el("run-error").textContent = "Could not reach the dashboard backend.";
    }
  }

  function setMode(mode) {
    document.querySelectorAll(".mode-tab").forEach((t) => {
      t.setAttribute("aria-selected", t.dataset.mode === mode ? "true" : "false");
    });
    document.querySelectorAll("[data-mode-panel]").forEach((p) => {
      p.hidden = p.dataset.modePanel !== mode;
    });
    const exampleMode = mode === "example";
    document.querySelectorAll('input[name="toolchain"], input[name="optimization"]').forEach((inp) => {
      inp.disabled = exampleMode;
    });
    el("config-panel").querySelector(".field-hint") ||
      null;
    const hint = el("config-toolchain-hint");
    if (hint) hint.hidden = !exampleMode;
    const ubsanHint = el("ubsan-example-hint");
    if (ubsanHint) ubsanHint.hidden = !exampleMode;
    const ubsanBox = el("enable-ubsan");
    if (exampleMode) {
      ubsanBox.disabled = true;
      const sid = el("example-select").value;
      ubsanBox.checked = !!(boot.example_ubsan && boot.example_ubsan[sid]);
    } else {
      ubsanBox.disabled = false;
    }
    scheduleRefreshPlan();
  }

  function init() {
    renderHeaderChips();
    renderToolchains();
    renderExamples();
    renderGeneratedPrograms();
    renderUbsan();
    el("custom-source").value = boot.custom_default_source;

    document.querySelectorAll(".mode-tab").forEach((tab) => {
      tab.addEventListener("click", () => setMode(tab.dataset.mode));
    });

    ["example-select", "generated-program", "generated-seed", "generated-count"].forEach((id) => {
      el(id).addEventListener("change", scheduleRefreshPlan);
      el(id).addEventListener("input", scheduleRefreshPlan);
    });
    el("custom-source").addEventListener("input", scheduleRefreshPlan);
    el("custom-stdin").addEventListener("input", scheduleRefreshPlan);
    document.getElementById("config-panel").addEventListener("change", scheduleRefreshPlan);

    el("run-btn").addEventListener("click", startRun);

    loadExampleSource();
    setMode("example");

    if (boot.busy) {
      el("run-status-text").textContent = "Another verification is in progress on the server.";
      showRunning(true);
      busyPollTimer = setInterval(async () => {
        try {
          const res = await fetch("/api/bootstrap");
          const data = await res.json();
          if (!data.busy) {
            clearInterval(busyPollTimer);
            showRunning(false);
          }
        } catch (_) {
          /* ignore */
        }
      }, 2000);
    }
    el("example-select").addEventListener("change", () => {
      if (document.querySelector('.mode-tab[aria-selected="true"]').dataset.mode === "example") {
        const sid = el("example-select").value;
        el("enable-ubsan").checked = !!(boot.example_ubsan && boot.example_ubsan[sid]);
      }
    });
  }

  init();
})();
