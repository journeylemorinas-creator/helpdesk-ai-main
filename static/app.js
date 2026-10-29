/* HelpDesk AI front end. Plain JavaScript (ES6) + Bootstrap 5. */
const HelpDesk = (() => {
  const csrf = () => document.querySelector('meta[name="csrf-token"]').content;

  // Escape text before putting it in HTML (prevents XSS from ticket content).
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const slug = (s) => String(s).replace(/\s+/g, "-");
  const priBadge = (p) => `<span class="badge badge-pri-${slug(p)}">${esc(p)}</span>`;
  const stBadge = (s) => `<span class="badge badge-st-${slug(s)}">${esc(s)}</span>`;

  async function api(method, url, body) {
    const opts = { method, headers: { Accept: "application/json" }, credentials: "same-origin" };
    if (method !== "GET") opts.headers["X-CSRF-Token"] = csrf();
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      throw { status: 0, error: "Cannot reach the server. Check your connection." };
    }
    if (res.status === 401) { window.location = "/login"; throw { status: 401, error: "Please log in." }; }
    let data = {};
    try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
    if (!res.ok) throw { status: res.status, error: data.error || "Something went wrong.", fields: data.fields || {} };
    return data;
  }

  function showFieldErrors(form, errBox, err) {
    form.querySelectorAll(".is-invalid").forEach((el) => el.classList.remove("is-invalid"));
    const fields = err.fields || {};
    Object.entries(fields).forEach(([name, msg]) => {
      const input = form.elements[name];
      if (input) {
        input.classList.add("is-invalid");
        const fb = input.parentElement.querySelector(".invalid-feedback");
        if (fb) fb.textContent = msg;
      }
    });
    errBox.textContent = err.error;
    errBox.classList.remove("d-none");
  }

  function clearErrors(form, errBox) {
    form.querySelectorAll(".is-invalid").forEach((el) => el.classList.remove("is-invalid"));
    errBox.classList.add("d-none");
  }

  function triageHtml(t, heading = "Triage suggestion") {
    const kws = t.keywords.length ? t.keywords.map((k) => `<span class="kw">${esc(k)}</span>`).join("") : "";
    return `
      <div class="fw-semibold mb-1"><i class="bi bi-stars me-1"></i>${esc(heading)}</div>
      <div class="mb-2">Category <strong>${esc(t.category)}</strong> &middot; Priority ${priBadge(t.priority)}</div>
      ${kws ? `<div class="mb-2 small">Matched: ${kws}</div>` : ""}
      <div class="small text-muted mb-2">${t.reasons.map(esc).join("<br>")}</div>
      <div class="small fw-semibold">First-line steps</div>
      <ul class="small mb-0">${t.suggestions.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>`;
  }

  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  // ------------------------------------------------------------------ dashboard
  function initDashboard() {
    const $ = (id) => document.getElementById(id);
    const rows = $("ticketRows");

    async function load() {
      const p = new URLSearchParams();
      if ($("q").value.trim()) p.set("q", $("q").value.trim());
      if ($("fStatus").value) p.set("status", $("fStatus").value);
      if ($("fCategory").value) p.set("category", $("fCategory").value);
      if ($("fPriority").value) p.set("priority", $("fPriority").value);
      try {
        const data = await api("GET", "/api/tickets?" + p);
        const s = data.summary;
        $("sTotal").textContent = s.total;
        $("sOpen").textContent = s["Open"];
        $("sProgress").textContent = s["In Progress"];
        $("sUrgent").textContent = s.urgent_open;
        $("sDone").textContent = s["Resolved"] + s["Closed"];
        if (!data.tickets.length) {
          rows.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">No tickets match.</td></tr>`;
          return;
        }
        rows.innerHTML = data.tickets.map((t) => `
          <tr>
            <td class="text-muted">#${t.id}</td>
            <td>
              <a class="ticket-link" href="/tickets/${t.id}">${esc(t.title)}</a>
              <div class="row-meta">${esc(t.requester_name)}${t.comment_count ? ` &middot; <i class="bi bi-chat-left-text"></i> ${t.comment_count}` : ""}</div>
            </td>
            <td>${esc(t.category)}</td>
            <td>${priBadge(t.priority)}</td>
            <td>${stBadge(t.status)}</td>
            <td class="text-end row-meta">${esc(t.updated_at.slice(0, 16))}</td>
          </tr>`).join("");
      } catch (err) {
        rows.innerHTML = `<tr><td colspan="6" class="text-center text-danger py-4">${esc(err.error)}</td></tr>`;
      }
    }

    const reload = debounce(load, 250);
    $("q").addEventListener("input", reload);
    ["fStatus", "fCategory", "fPriority"].forEach((id) => $(id).addEventListener("change", load));
    $("btnClear").addEventListener("click", () => {
      $("q").value = ""; ["fStatus", "fCategory", "fPriority"].forEach((id) => ($(id).value = ""));
      load();
    });

    // new ticket form with live triage preview
    const form = $("ticketForm"), errBox = $("formError"), preview = $("triagePreview");
    const updatePreview = debounce(async () => {
      const title = form.elements.title.value, description = form.elements.description.value;
      if (title.trim().length < 3 && description.trim().length < 3) return;
      try {
        const t = await api("POST", "/api/triage", { title, description });
        preview.innerHTML = triageHtml(t);
      } catch (e) { /* preview is optional */ }
    }, 350);
    form.elements.title.addEventListener("input", updatePreview);
    form.elements.description.addEventListener("input", updatePreview);

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      clearErrors(form, errBox);
      const body = Object.fromEntries(new FormData(form).entries());
      try {
        const res = await api("POST", "/api/tickets", body);
        window.location = "/tickets/" + res.id;
      } catch (err) { showFieldErrors(form, errBox, err); }
    });
    document.getElementById("ticketModal").addEventListener("hidden.bs.modal", () => {
      form.reset(); clearErrors(form, errBox);
      preview.innerHTML = `<div class="fw-semibold mb-1"><i class="bi bi-stars me-1"></i>Triage suggestion</div>
        <div class="text-muted small">Type a title and description to see the suggested category, priority and first steps.</div>`;
    });

    load();
  }

  // ------------------------------------------------------------------ ticket page
  function initTicket(statuses) {
    const root = document.getElementById("ticketRoot");
    const id = root.dataset.ticketId;
    const editForm = document.getElementById("editForm"), editErr = document.getElementById("editError");
    const modal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById("editModal"));
    let current = null;

    function render(data) {
      current = data.ticket;
      const t = data.ticket, ai = data.triage;
      const differs = ai.category !== t.category || ai.priority !== t.priority;
      root.innerHTML = `
        <div class="row g-4">
          <div class="col-lg-8">
            <div class="card shadow-sm mb-4"><div class="card-body">
              <div class="d-flex flex-wrap justify-content-between gap-2">
                <div>
                  <div class="text-muted small">Ticket #${t.id}</div>
                  <h1 class="h4 mb-2">${esc(t.title)}</h1>
                  <div class="mb-2">${stBadge(t.status)} ${priBadge(t.priority)} <span class="badge text-bg-light border">${esc(t.category)}</span></div>
                </div>
                <div class="d-flex gap-2 align-items-start">
                  <button class="btn btn-sm btn-outline-primary" id="btnEdit"><i class="bi bi-pencil"></i> Edit</button>
                  <button class="btn btn-sm btn-outline-danger" id="btnDelete"><i class="bi bi-trash"></i> Delete</button>
                </div>
              </div>
              <p class="desc mt-2">${esc(t.description)}</p>
              <div class="row-meta">Requested by ${esc(t.requester_name)}${t.requester_email ? ` (${esc(t.requester_email)})` : ""}
                &middot; created ${esc(t.created_at.slice(0, 16))} &middot; updated ${esc(t.updated_at.slice(0, 16))}</div>
              <hr>
              <div class="d-flex flex-wrap align-items-center gap-2">
                <span class="small fw-semibold">Set status:</span>
                ${statuses.map((s) => `<button class="btn btn-sm ${s === t.status ? "btn-primary" : "btn-outline-secondary"}" data-status="${esc(s)}">${esc(s)}</button>`).join("")}
              </div>
              <div class="text-danger small mt-2 d-none" id="statusError"></div>
            </div></div>

            <div class="card shadow-sm"><div class="card-body">
              <h2 class="h6">Comments (${data.comments.length})</h2>
              <div id="commentList">${data.comments.length ? data.comments.map((c) => `
                <div class="comment">
                  <div class="d-flex justify-content-between">
                    <span class="small fw-semibold">${esc(c.author_name)} <span class="text-muted fw-normal">&middot; ${esc(c.created_at.slice(0, 16))}</span></span>
                    <button class="btn btn-sm btn-link text-danger p-0" data-del-comment="${c.id}" aria-label="Delete comment"><i class="bi bi-x-lg"></i></button>
                  </div>
                  <div class="desc">${esc(c.body)}</div>
                </div>`).join("") : `<p class="text-muted small">No comments yet.</p>`}</div>
              <form id="commentForm" class="mt-3" novalidate>
                <label class="visually-hidden" for="commentBody">Add a comment</label>
                <textarea class="form-control" id="commentBody" name="body" rows="2" maxlength="1000" placeholder="Add a note for the team"></textarea>
                <div class="invalid-feedback"></div>
                <button class="btn btn-sm btn-primary mt-2" type="submit">Add comment</button>
              </form>
            </div></div>
          </div>

          <div class="col-lg-4">
            <div class="triage-box">
              ${triageHtml(ai, "AI triage assessment")}
              ${differs ? `<div class="small mt-2 text-muted"><i class="bi bi-info-circle"></i> The suggestion differs from the category/priority a technician set. That is fine: the technician decides.</div>` : ""}
            </div>
          </div>
        </div>`;

      document.getElementById("btnEdit").addEventListener("click", openEdit);
      document.getElementById("btnDelete").addEventListener("click", removeTicket);
      root.querySelectorAll("[data-status]").forEach((b) => b.addEventListener("click", () => setStatus(b.dataset.status)));
      root.querySelectorAll("[data-del-comment]").forEach((b) => b.addEventListener("click", () => delComment(b.dataset.delComment)));
      document.getElementById("commentForm").addEventListener("submit", addComment);
    }

    async function load() {
      try { render(await api("GET", `/api/tickets/${id}`)); }
      catch (err) { root.innerHTML = `<div class="alert alert-danger">${esc(err.error)}</div>`; }
    }

    function openEdit() {
      clearErrors(editForm, editErr);
      ["title", "description", "requester_name", "requester_email", "category", "priority", "status"]
        .forEach((k) => (editForm.elements[k].value = current[k] ?? ""));
      modal().show();
    }

    editForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      clearErrors(editForm, editErr);
      try {
        await api("PUT", `/api/tickets/${id}`, Object.fromEntries(new FormData(editForm).entries()));
        modal().hide();
        load();
      } catch (err) { showFieldErrors(editForm, editErr, err); }
    });

    async function setStatus(status) {
      try { await api("PUT", `/api/tickets/${id}/status`, { status }); load(); }
      catch (err) {
        const box = document.getElementById("statusError");
        box.textContent = err.error; box.classList.remove("d-none");
      }
    }

    async function removeTicket() {
      if (!confirm("Delete this ticket and its comments? This cannot be undone.")) return;
      try { await api("DELETE", `/api/tickets/${id}`); window.location = "/dashboard"; }
      catch (err) { alert(err.error); }
    }

    async function addComment(ev) {
      ev.preventDefault();
      const form = ev.target, box = form.elements.body;
      box.classList.remove("is-invalid");
      try {
        await api("POST", `/api/tickets/${id}/comments`, { body: box.value });
        load();
      } catch (err) {
        box.classList.add("is-invalid");
        form.querySelector(".invalid-feedback").textContent = (err.fields && err.fields.body) || err.error;
      }
    }

    async function delComment(cid) {
      try { await api("DELETE", `/api/comments/${cid}`); load(); } catch (err) { alert(err.error); }
    }

    load();
  }

  return { initDashboard, initTicket };
})();
