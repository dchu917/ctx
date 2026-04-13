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

function formatDate(value) {
  if (!value) {
    return "unknown date";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function sourceLabel(item) {
  const sources = Array.isArray(item.sources) ? item.sources : [];
  if (sources.includes("codex") && sources.includes("claude")) {
    return "both";
  }
  if (sources.includes("codex")) {
    return "codex";
  }
  if (sources.includes("claude")) {
    return "claude";
  }
  return "other";
}

function currentSlugFromPath() {
  const match = window.location.pathname.match(/^\/workstreams\/(.+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function renderShell(content) {
  document.getElementById("app-view").innerHTML = content;
}

function renderListPage(items) {
  const cards = items.length
    ? items
        .map((item) => {
          const latest = item.latest || "No recent task recorded yet.";
          return `
            <a class="ws-link" href="/workstreams/${encodeURIComponent(item.slug)}" data-nav="${escapeHtml(item.slug)}">
              <article class="ws-card">
                <div class="ws-row">
                  <div>
                    <div class="ws-title">${escapeHtml(item.title)}</div>
                    <div class="ws-slug">${escapeHtml(item.slug)}</div>
                    <div class="ws-copy">This workstream was focused on ${escapeHtml(item.goal || item.title)}. Most recent task: ${escapeHtml(latest)}</div>
                  </div>
                  <div class="ws-meta">
                    <span class="pill">${escapeHtml(formatDate(item.last_activity_at))}</span>
                    <span class="pill source">${escapeHtml(sourceLabel(item))}</span>
                  </div>
                </div>
              </article>
            </a>
          `;
        })
        .join("")
    : `<div class="empty-state">No workstreams found.</div>`;

  renderShell(`
    <section class="panel">
      <div class="panel-head">
        <h2>Workstreams</h2>
        <span class="panel-note">${items.length} streams</span>
      </div>
      <div id="workstream-list" class="workstream-list">${cards}</div>
    </section>
  `);

  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const slug = link.getAttribute("data-nav");
      window.history.pushState({}, "", `/workstreams/${encodeURIComponent(slug)}`);
      boot().catch(showError);
    });
  });
}

function commandBlock(label, command) {
  return `
    <div class="command-card">
      <p class="label">${escapeHtml(label)}</p>
      <pre>${escapeHtml(command)}</pre>
    </div>
  `;
}

function recentItem(entry) {
  const role = entry.role ? ` / ${entry.role}` : "";
  const mode = entry.load_behavior || "default";
  return `
    <article class="recent-item ${mode === "exclude" ? "is-excluded" : ""}">
      <div class="recent-head">
        <strong>S${entry.session_id} ${escapeHtml(entry.type)}${escapeHtml(role)}</strong>
        <div class="recent-meta">
          <span class="pill load ${escapeHtml(mode)}">${escapeHtml(mode)}</span>
          <span class="muted">${escapeHtml(formatDate(entry.created_at))}</span>
        </div>
      </div>
      <div class="muted">${escapeHtml(entry.session_title)}</div>
      <div class="value">${escapeHtml(entry.preview)}</div>
      <div class="entry-controls">
        <button type="button" class="entry-button" data-load-mode="${escapeHtml(mode === "pin" ? "default" : "pin")}" data-entry-id="${entry.id}">
          ${mode === "pin" ? "Unpin" : "Pin"}
        </button>
        <button type="button" class="entry-button" data-load-mode="${escapeHtml(mode === "exclude" ? "default" : "exclude")}" data-entry-id="${entry.id}">
          ${mode === "exclude" ? "Include" : "Exclude"}
        </button>
        <button type="button" class="entry-button danger" data-entry-delete="${entry.id}">
          Delete
        </button>
      </div>
    </article>
  `;
}

function renderDetailPage(detail, listItem) {
  const ws = detail.workstream;
  const latest = detail.recent_entries[0]?.preview || listItem?.latest || "No recent task recorded yet.";
  renderShell(`
    <section class="panel detail-page">
      <div class="panel-head">
        <a href="/" id="back-link" class="back-link">← Back to workstreams</a>
        <span class="panel-note">${escapeHtml(formatDate(listItem?.last_activity_at || ws.created_at))} · ${escapeHtml(sourceLabel(listItem || {}))}</span>
      </div>
      <div class="detail-header">
        <div>
          <h2>${escapeHtml(ws.title)}</h2>
          <div class="ws-slug">${escapeHtml(ws.slug)}</div>
        </div>
      </div>

      <div class="info-grid">
        <div class="info-card">
          <p class="label">What This Workstream Did</p>
          <p class="value">${escapeHtml(ws.goal || ws.title)}</p>
        </div>
        <div class="info-card">
          <p class="label">Most Recent Task</p>
          <p class="value">${escapeHtml(latest)}</p>
        </div>
      </div>

      <div class="command-grid">
        ${commandBlock("Continue In Claude Code", `/ctx resume ${ws.slug}`)}
        ${commandBlock("Continue In Codex", `ctx resume ${ws.slug}`)}
      </div>

      <section class="detail-section">
        <p class="label">Rename Workstream</p>
        <div class="rename-row">
          <input id="rename-input" type="text" value="${escapeHtml(ws.title)}" />
          <button id="rename-button" class="rename-button" type="button">Rename</button>
        </div>
        <p class="panel-note">If you later start another workstream with this same name, ctx will save it as <code>${escapeHtml(ws.title)} (1)</code>.</p>
      </section>

      <section class="detail-section">
        <p class="label">Recent Context</p>
        <p class="panel-note">Pinned entries always load in future ctx packs. Excluded entries stay saved and searchable, but they will not be loaded next time.</p>
        <p class="panel-note">${ws.pinned_count || 0} pinned · ${ws.excluded_count || 0} excluded</p>
        <div class="recent-list">
          ${
            detail.recent_entries.length
              ? detail.recent_entries.map(recentItem).join("")
              : `<div class="empty-state">No recent context saved yet.</div>`
          }
        </div>
      </section>
    </section>
  `);

  document.getElementById("back-link").addEventListener("click", (event) => {
    event.preventDefault();
    window.history.pushState({}, "", "/");
    boot().catch(showError);
  });

  document.getElementById("rename-button").addEventListener("click", async () => {
    const newName = document.getElementById("rename-input").value.trim();
    if (!newName) {
      return;
    }
    const result = await api("/api/actions/rename", {
      method: "POST",
      body: JSON.stringify({ ref: ws.slug, new_name: newName }),
    });
    const nextSlug =
      result?.detail?.workstream?.slug ||
      result?.current?.slug ||
      slugifyForPath(newName);
    window.history.pushState({}, "", `/workstreams/${encodeURIComponent(nextSlug)}`);
    boot().catch(showError);
  });

  document.querySelectorAll("[data-load-mode]").forEach((button) => {
    button.addEventListener("click", async () => {
      const entryId = Number(button.getAttribute("data-entry-id"));
      const mode = button.getAttribute("data-load-mode");
      await api("/api/entries/load-behavior", {
        method: "POST",
        body: JSON.stringify({ entry_id: entryId, mode }),
      });
      boot().catch(showError);
    });
  });

  document.querySelectorAll("[data-entry-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      const entryId = Number(button.getAttribute("data-entry-delete"));
      if (!window.confirm(`Delete saved entry ${entryId}? This cannot be undone.`)) {
        return;
      }
      await api("/api/entries/delete", {
        method: "POST",
        body: JSON.stringify({ entry_id: entryId }),
      });
      boot().catch(showError);
    });
  });
}

function showError(error) {
  renderShell(`<div class="empty-state">${escapeHtml(error.message || String(error))}</div>`);
}

async function boot() {
  const query = document.getElementById("filter-query").value.trim();
  const payload = await api(query ? `/api/workstreams?query=${encodeURIComponent(query)}` : "/api/workstreams");
  const slug = currentSlugFromPath();
  if (slug) {
    const detail = await api(`/api/workstreams/${encodeURIComponent(slug)}`);
    const listItem = payload.items.find((item) => item.slug === slug) || null;
    renderDetailPage(detail, listItem);
    return;
  }
  renderListPage(payload.items);
}

function bindEvents() {
  const input = document.getElementById("filter-query");
  input.addEventListener("input", async () => {
    if (currentSlugFromPath()) {
      window.history.replaceState({}, "", "/");
    }
    await boot().catch(showError);
  });
  window.addEventListener("popstate", () => {
    boot().catch(showError);
  });
}

function slugifyForPath(name) {
  return String(name || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "") || "ws";
}

bindEvents();
boot().catch(showError);
