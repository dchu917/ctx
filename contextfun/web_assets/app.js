const state = {
  current: null,
  selectedSlug: null,
  latestAction: null,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data.error || data.stderr || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return data;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function slugMarkup(slug) {
  return `<span class="slug">${escapeHtml(slug)}</span>`;
}

function renderCurrent(status) {
  const el = document.getElementById("current-workstream");
  const dbPath = document.getElementById("db-path");
  const current = status?.current || state.current;
  if (status?.current !== undefined) {
    state.current = status.current;
  }
  if (status?.db_path) {
    dbPath.textContent = status.db_path;
  }
  if (!current) {
    el.innerHTML = `<div class="empty-state">No current workstream set.</div>`;
    return;
  }
  el.innerHTML = `
    <div class="current-chip">Current: ${escapeHtml(current.slug)}</div>
    <p class="muted">${escapeHtml(current.title)}</p>
  `;
}

function workstreamCard(item) {
  return `
    <article class="ws-card ${state.selectedSlug === item.slug ? "is-selected" : ""}" data-slug="${escapeHtml(item.slug)}">
      <div class="ws-top">
        <div>
          <div class="workstream-title">${escapeHtml(item.title)}</div>
          ${slugMarkup(item.slug)}
        </div>
        ${item.current ? `<span class="pill current">current</span>` : ""}
      </div>
      <div class="ws-meta">
        <div class="pill-row">
          <span class="pill">${item.session_count} sessions</span>
          <span class="pill">${item.entry_count} entries</span>
        </div>
        <div class="ws-summary">
          <strong>Goal</strong>
          <span>${escapeHtml(item.goal)}</span>
        </div>
        <div class="ws-summary">
          <strong>Latest</strong>
          <span>${escapeHtml(item.latest)}</span>
        </div>
      </div>
    </article>
  `;
}

function renderWorkstreams(items) {
  const list = document.getElementById("workstream-list");
  if (!items.length) {
    list.innerHTML = `<div class="empty-state">No workstreams yet.</div>`;
    return;
  }
  list.innerHTML = items.map(workstreamCard).join("");
  list.querySelectorAll(".ws-card").forEach((card) => {
    card.addEventListener("click", () => {
      selectWorkstream(card.dataset.slug);
    });
  });
}

function sessionCard(session) {
  const links = session.links.length
    ? `<div class="pill-row">${session.links
        .map((link) => `<span class="pill">${escapeHtml(`${link.source}:${link.external_session_id}`)}</span>`)
        .join("")}</div>`
    : `<div class="muted">Detached session</div>`;
  return `
    <article class="session-card">
      <div class="session-top">
        <strong>S${session.id} ${escapeHtml(session.title)}</strong>
        <span class="muted">${escapeHtml(session.created_at)}</span>
      </div>
      <div class="pill-row">
        <span class="pill">@${escapeHtml(session.agent)}</span>
        <span class="pill">${session.entry_count} entries</span>
      </div>
      <div class="session-links">${links}</div>
    </article>
  `;
}

function entryCard(entry) {
  return `
    <article class="entry-card">
      <div class="entry-top">
        <strong>S${entry.session_id} ${escapeHtml(entry.type)}</strong>
        <span class="muted">${escapeHtml(entry.created_at)}</span>
      </div>
      <div class="muted">${escapeHtml(entry.session_title)}</div>
      <p class="entry-preview">${escapeHtml(entry.preview)}</p>
    </article>
  `;
}

function renderDetail(detail) {
  const root = document.getElementById("workstream-detail");
  const hint = document.getElementById("selected-hint");
  if (!detail) {
    root.innerHTML = `<div class="empty-state">No workstream selected yet.</div>`;
    hint.textContent = "Choose a workstream from the left.";
    return;
  }
  const ws = detail.workstream;
  state.selectedSlug = ws.slug;
  hint.textContent = ws.current ? "This workstream is current." : "Select an action below.";
  root.innerHTML = `
    <div class="detail-head">
      <div class="detail-title-block">
        <h3>${escapeHtml(ws.title)}</h3>
        ${slugMarkup(ws.slug)}
      </div>
      <div class="detail-actions">
        <button class="button button-secondary" id="set-current-button">Set Current</button>
        <button class="button button-primary" id="resume-button">Resume</button>
        <button class="button button-danger" id="delete-button">Delete Latest Session</button>
      </div>
    </div>

    <div class="meta-grid">
      <div class="meta-card">
        <p class="meta-label">Goal</p>
        <p class="meta-value">${escapeHtml(ws.goal)}</p>
      </div>
      <div class="meta-card">
        <p class="meta-label">Workspace</p>
        <p class="meta-value">${escapeHtml(ws.workspace || "n/a")}</p>
      </div>
      <div class="meta-card">
        <p class="meta-label">Summary</p>
        <p class="meta-value">${escapeHtml(ws.summary)}</p>
      </div>
      <div class="meta-card">
        <p class="meta-label">Created</p>
        <p class="meta-value">${escapeHtml(ws.created_at)}</p>
      </div>
    </div>

    <div class="detail-sections">
      <section class="detail-section">
        <div class="panel-head">
          <h4>Branch</h4>
        </div>
        <div class="inline-actions">
          <input id="branch-target" type="text" placeholder="feature-audit-v2" />
          <button class="button button-secondary" id="branch-button">Create Branch</button>
        </div>
      </section>

      <section class="detail-section">
        <h4>Sessions</h4>
        <div class="session-grid">
          ${detail.sessions.length ? detail.sessions.map(sessionCard).join("") : `<div class="empty-state">No sessions yet.</div>`}
        </div>
      </section>

      <section class="detail-section">
        <h4>Recent Entries</h4>
        <div class="entry-grid">
          ${detail.recent_entries.length ? detail.recent_entries.map(entryCard).join("") : `<div class="empty-state">No recent entries yet.</div>`}
        </div>
      </section>
    </div>
  `;

  document.getElementById("set-current-button").addEventListener("click", async () => {
    await api("/api/current", {
      method: "POST",
      body: JSON.stringify({ slug: ws.slug }),
    });
    await refreshStatus();
    await loadWorkstreams();
    await selectWorkstream(ws.slug);
  });

  document.getElementById("resume-button").addEventListener("click", async () => {
    await runAction("/api/actions/resume", { name: ws.slug, source: document.getElementById("start-source").value });
  });

  document.getElementById("delete-button").addEventListener("click", async () => {
    if (!window.confirm(`Delete the latest session in ${ws.slug}?`)) {
      return;
    }
    await runAction("/api/actions/delete", { name: ws.slug });
    await refreshStatus();
    await loadWorkstreams();
    await selectWorkstream(ws.slug);
  });

  document.getElementById("branch-button").addEventListener("click", async () => {
    const target = document.getElementById("branch-target").value.trim();
    if (!target) {
      window.alert("Provide a target workstream name.");
      return;
    }
    await runAction("/api/actions/branch", {
      source_name: ws.slug,
      target_name: target,
      agent: document.getElementById("start-agent").value,
    });
    await refreshStatus();
    await loadWorkstreams();
    await selectWorkstream(target);
  });
}

function renderSearchResults(payload) {
  const root = document.getElementById("search-results");
  if (!payload.query) {
    root.innerHTML = "";
    return;
  }
  const modeLine =
    payload.mode === "loose-or"
      ? `<div class="muted">Loose OR fallback was used because the strict search had no hits.</div>`
      : "";
  const workstreams = payload.workstreams.length
    ? payload.workstreams
        .map(
          (item) => `
          <article class="result-card" data-slug="${escapeHtml(item.slug)}">
            <strong>${escapeHtml(item.slug)}</strong>
            <div class="muted">${escapeHtml(item.summary || item.title)}</div>
            <div class="best-snippet">${escapeHtml(item.snippet)}</div>
          </article>
        `
        )
        .join("")
    : `<div class="empty-state">No workstream matches.</div>`;
  const matches = payload.matches.length
    ? payload.matches
        .map(
          (item) => `
          <article class="result-card">
            <strong>${escapeHtml(item.workstream_slug || "(unscoped)")}</strong>
            <div class="muted">${escapeHtml(item.kind)} · ${escapeHtml(item.created_at)}</div>
            <div class="match-snippet">${escapeHtml(item.snippet)}</div>
          </article>
        `
        )
        .join("")
    : "";
  root.innerHTML = `
    ${modeLine}
    <div class="stack">
      <div>
        <strong>Top workstreams</strong>
        <div class="search-results">${workstreams}</div>
      </div>
      <div>
        <strong>Top matches</strong>
        <div class="search-results">${matches}</div>
      </div>
    </div>
  `;
  root.querySelectorAll("[data-slug]").forEach((card) => {
    card.addEventListener("click", () => {
      selectWorkstream(card.dataset.slug);
    });
  });
}

function renderActionResult(result) {
  const root = document.getElementById("action-result");
  if (!result) {
    root.innerHTML = `<div class="empty-state">Start or resume a workstream to inspect the full loaded pack here.</div>`;
    return;
  }
  const statusClass = result.ok ? "status-ok" : "status-error";
  const parsed = result.parsed || { summary: result.stdout || "", pack: "" };
  root.innerHTML = `
    <div class="load-summary">
      <div class="${statusClass}"><strong>${result.ok ? "Action completed" : "Action failed"}</strong></div>
      <pre>${escapeHtml(parsed.summary || result.stderr || "")}</pre>
    </div>
    <div class="load-pack">
      <details ${parsed.pack ? "" : "open"}>
        <summary>${parsed.pack ? "Expand full ctx pack" : "Inspect raw command output"}</summary>
        <pre>${escapeHtml(parsed.pack || result.stdout || result.stderr || "")}</pre>
      </details>
    </div>
  `;
}

async function refreshStatus() {
  const status = await api("/api/status");
  state.current = status.current;
  renderCurrent(status);
  return status;
}

async function loadWorkstreams(query = "") {
  const url = query ? `/api/workstreams?query=${encodeURIComponent(query)}` : "/api/workstreams";
  const payload = await api(url);
  renderWorkstreams(payload.items);
  if (!state.selectedSlug) {
    const preferred = state.current?.slug || payload.items[0]?.slug;
    if (preferred) {
      await selectWorkstream(preferred);
    }
  }
}

async function selectWorkstream(slug) {
  if (!slug) {
    return;
  }
  state.selectedSlug = slug;
  const detail = await api(`/api/workstreams/${encodeURIComponent(slug)}`);
  renderDetail(detail);
  const nameInput = document.getElementById("start-name");
  nameInput.value = slug;
  await loadWorkstreams(document.getElementById("search-query").value.trim());
}

async function runAction(path, payload) {
  const result = await api(path, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.latestAction = result;
  renderActionResult(result);
  if (result.current) {
    state.current = result.current;
    renderCurrent({ current: result.current, db_path: document.getElementById("db-path").textContent });
  }
  if (result.detail?.workstream?.slug) {
    await selectWorkstream(result.detail.workstream.slug);
  }
  return result;
}

function bindEvents() {
  document.getElementById("refresh-workstreams").addEventListener("click", async () => {
    await loadWorkstreams(document.getElementById("search-query").value.trim());
  });

  document.getElementById("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = document.getElementById("search-query").value.trim();
    const payload = await api(`/api/search?q=${encodeURIComponent(query)}&limit=8`);
    renderSearchResults(payload);
  });

  document.getElementById("start-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = document.getElementById("start-name").value.trim();
    if (!name) {
      window.alert("Provide a workstream name.");
      return;
    }
    await runAction("/api/actions/start", {
      name,
      agent: document.getElementById("start-agent").value,
      source: document.getElementById("start-source").value,
      pasted_text: document.getElementById("start-pasted-text").value,
    });
    document.getElementById("start-pasted-text").value = "";
    await refreshStatus();
    await loadWorkstreams(document.getElementById("search-query").value.trim());
  });

  document.getElementById("resume-selected").addEventListener("click", async () => {
    const name = document.getElementById("start-name").value.trim() || state.selectedSlug;
    if (!name) {
      window.alert("Choose a workstream to resume.");
      return;
    }
    await runAction("/api/actions/resume", {
      name,
      source: document.getElementById("start-source").value,
    });
  });
}

async function boot() {
  bindEvents();
  const status = await refreshStatus();
  document.getElementById("db-path").textContent = status.db_path;
  await loadWorkstreams();
}

boot().catch((error) => {
  renderActionResult({
    ok: false,
    stderr: error.message,
    stdout: "",
    parsed: { summary: error.message, pack: "" },
  });
});
