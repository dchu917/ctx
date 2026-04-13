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

function repoDisplay(item) {
  if (!item) {
    return { label: "repo unknown", detail: "No linked repo saved yet.", tone: "unknown" };
  }
  if (item.repo_relation === "current") {
    return {
      label: item.repo_name ? item.repo_name : "this repo",
      detail: item.workspace ? item.workspace : "Matches the repo you are currently in.",
      tone: "current",
    };
  }
  if (item.repo_name) {
    return {
      label: item.repo_name,
      detail: item.workspace || `Saved in ${item.repo_name}`,
      tone: "other",
    };
  }
  if (item.workspace) {
    return {
      label: "other repo",
      detail: item.workspace,
      tone: "other",
    };
  }
  return { label: "repo unknown", detail: "No linked repo saved yet.", tone: "unknown" };
}

function scopeFromUrl() {
  const url = new URL(window.location.href);
  const scope = url.searchParams.get("scope") || "current";
  return ["all", "current", "other"].includes(scope) ? scope : "current";
}

function setScopeInUrl(scope) {
  const url = new URL(window.location.href);
  if (!scope || scope === "all") {
    url.searchParams.delete("scope");
  } else {
    url.searchParams.set("scope", scope);
  }
  window.history.replaceState({}, "", `${url.pathname}${url.search}`);
}

function syncScopeButtons(scope) {
  document.querySelectorAll("[data-scope]").forEach((button) => {
    button.classList.toggle("is-active", button.getAttribute("data-scope") === scope);
  });
}

function currentSlugFromPath() {
  const match = window.location.pathname.match(/^\/workstreams\/(.+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function currentSearchSuffix() {
  const search = window.location.search || "";
  return search;
}

function renderShell(content) {
  document.getElementById("app-view").innerHTML = content;
}

function renderListPage(items) {
  const cards = items.length
    ? items
        .map((item) => {
          const latest = item.latest || "No recent task recorded yet.";
          const repo = repoDisplay(item);
          return `
            <a class="ws-link" href="/workstreams/${encodeURIComponent(item.slug)}" data-nav="${escapeHtml(item.slug)}">
              <article class="ws-card">
                <div class="ws-row">
                  <div>
                    <div class="ws-title">${escapeHtml(item.title)}</div>
                    <div class="ws-slug">${escapeHtml(item.slug)}</div>
                    <div class="ws-copy">This workstream was focused on ${escapeHtml(item.goal || item.title)}. Most recent task: ${escapeHtml(latest)}</div>
                    <div class="repo-link-row">
                      <span class="pill repo ${escapeHtml(repo.tone)}">linked repo: ${escapeHtml(repo.label)}</span>
                      <span class="repo-path">${escapeHtml(repo.detail)}</span>
                    </div>
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
      window.history.pushState({}, "", `/workstreams/${encodeURIComponent(slug)}${currentSearchSuffix()}`);
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
  const repo = repoDisplay(ws);
  const guardedResume = ws.repo_relation === "other" ? `ctx resume ${ws.slug} --allow-other-repo` : `ctx resume ${ws.slug}`;
  const guardedClaudeResume = ws.repo_relation === "other" ? `/ctx resume ${ws.slug} --allow-other-repo` : `/ctx resume ${ws.slug}`;
  const repoText =
    ws.repo_relation === "current"
      ? "This workstream matches the repo you are currently in."
      : ws.workspace
        ? `Warning: this workstream was saved in ${ws.workspace}.`
        : "Repo is unknown for this workstream.";
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
          <div class="detail-repo-row">
            <span class="pill repo ${escapeHtml(repo.tone)}">linked repo: ${escapeHtml(repo.label)}</span>
            <span class="repo-path">${escapeHtml(repo.detail)}</span>
          </div>
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
        <div class="info-card">
          <p class="label">Repo</p>
          <p class="value">${escapeHtml(repoText)}</p>
        </div>
      </div>

      ${
        ws.repo_relation === "other"
          ? `<div class="guardrail-note">
              This workstream is linked to another repo. Resume is blocked by default here.
              Use the explicit override only if you really want to continue it in this repo.
            </div>`
          : ""
      }

      <div class="command-grid">
        ${commandBlock("Continue In Claude Code", guardedClaudeResume)}
        ${commandBlock("Continue In Codex", guardedResume)}
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
    window.history.pushState({}, "", `/${currentSearchSuffix()}`);
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
    window.history.pushState({}, "", `/workstreams/${encodeURIComponent(nextSlug)}${currentSearchSuffix()}`);
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
  const scope = scopeFromUrl();
  syncScopeButtons(scope);
  const params = new URLSearchParams();
  if (query) {
    params.set("query", query);
  }
  if (scope !== "all") {
    params.set("scope", scope);
  }
  const payload = await api(params.toString() ? `/api/workstreams?${params.toString()}` : "/api/workstreams");
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
      const url = new URL(window.location.href);
      window.history.replaceState({}, "", `/${url.search}`);
    }
    await boot().catch(showError);
  });
  document.querySelectorAll("[data-scope]").forEach((button) => {
    button.addEventListener("click", async () => {
      setScopeInUrl(button.getAttribute("data-scope") || "all");
      if (currentSlugFromPath()) {
        const url = new URL(window.location.href);
        window.history.replaceState({}, "", `/${url.search}`);
      }
      await boot().catch(showError);
    });
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
