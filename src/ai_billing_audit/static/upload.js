/* Encounter upload portal — frontend logic.
 *
 * Wires the four input modes (837P / ZIP / clinical note / paste-form)
 * to the FastAPI routes the dashboard ships, drives the parse-preview
 * table, the submit button, and the job-status polling loop.
 *
 * No external dependencies. The page itself is served at
 * /encounters/upload by templates/encounters_upload.html.
 */
(function () {
  "use strict";

  // ---- element refs ----------------------------------------------------

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const tabs = $$(".upload-tab");
  const panels = {
    "tab-837p": $("#tab-837p"),
    "tab-zip": $("#tab-zip"),
    "tab-note": $("#tab-note"),
    "tab-paste": $("#tab-paste"),
  };
  const dropzones = $$(".dropzone");
  const previewPanel = $("#preview-panel");
  const previewTbody = $("#preview-tbody");
  const previewSummary = $("#preview-summary");
  const previewRaw = $("#preview-raw");
  const previewRawWrap = $("#preview-raw-wrap");
  const btnSubmit = $("#btn-submit");
  const btnClear = $("#btn-clear");
  const btnPastePreview = $("#btn-paste-preview");
  const submitSummary = $("#submit-summary");
  const jobsPanel = $("#jobs-panel");
  const jobList = $("#job-list");
  const pasteForm = $("#paste-form");
  const noteStatus = $("#note-status");
  const rowTpl = $("#row-template");
  const jobTpl = $("#job-template");

  // ---- state -----------------------------------------------------------

  let previewRows = []; // rows from /preview or /paste
  let pollers = {}; // job_id -> interval handle

  // ---- helpers ---------------------------------------------------------

  function showTab(targetId) {
    tabs.forEach((t) => {
      const on = t.dataset.target === targetId;
      t.classList.toggle("is-active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    Object.entries(panels).forEach(([id, el]) => {
      if (el) el.hidden = id !== targetId;
    });
  }

  function setSubmitEnabled() {
    const ok = previewRows.some((r) => !r.errors || r.errors.length === 0);
    btnSubmit.disabled = !ok;
  }

  function renderPreview() {
    previewTbody.replaceChildren();
    let ok = 0;
    let bad = 0;
    const rawSnippets = [];
    previewRows.forEach((row, idx) => {
      const tr = rowTpl.content.firstElementChild.cloneNode(true);
      tr.dataset.rowIdx = String(idx);
      tr.querySelector(".cell-enc").textContent = row.encounter_id || "";
      tr.querySelector(".cell-pid").textContent = row.patient_id || "";
      tr.querySelector(".cell-npi").textContent = row.NPI || "";
      tr.querySelector(".cell-dos").textContent = row.date_of_service || "";
      tr.querySelector(".cell-cpt").textContent = (row.CPT_codes || []).join(", ");
      tr.querySelector(".cell-source").textContent = row.source || row.source_filename || "";
      const statusCell = tr.querySelector(".cell-status");
      const errs = row.errors || [];
      if (errs.length) {
        bad += 1;
        // Build the rejected cell with createElement / textContent
        // so user-supplied text from errs[*] is never parsed as
        // HTML. The badge class is a fixed string.
        const badge = document.createElement("span");
        badge.className = "badge badge--flag";
        badge.textContent = "rejected";
        statusCell.appendChild(badge);
        statusCell.appendChild(document.createTextNode(" "));
        errs.forEach((e) => {
          const div = document.createElement("div");
          div.className = "cell-error";
          div.textContent = e;
          statusCell.appendChild(div);
        });
        tr.classList.add("row-bad");
      } else {
        ok += 1;
        const badge = document.createElement("span");
        badge.className = "badge badge--clean";
        badge.textContent = "accepted";
        statusCell.appendChild(badge);
        tr.classList.add("row-ok");
      }
      previewTbody.appendChild(tr);
      if (row.raw) {
        rawSnippets.push(
          "--- " + (row.source_filename || "(paste)") + " ---\n" + row.raw
        );
      }
    });
    previewSummary.textContent =
      previewRows.length === 0
        ? "No rows parsed yet."
        : `${ok} accepted, ${bad} rejected of ${previewRows.length} row(s).`;
    if (rawSnippets.length) {
      previewRaw.textContent = rawSnippets.join("\n\n");
      previewRawWrap.hidden = false;
    } else {
      previewRaw.textContent = "";
      previewRawWrap.hidden = true;
    }
    previewPanel.hidden = previewRows.length === 0;
    setSubmitEnabled();
  }

  function applyPreviewRows(rows, filename) {
    previewRows = Array.isArray(rows) ? rows : [];
    renderPreview();
    if (filename) submitSummary.textContent = "From: " + filename;
  }

  async function postForm(url, fd) {
    const r = await fetch(url, { method: "POST", body: fd });
    const text = await r.text();
    let body;
    try {
      body = JSON.parse(text);
    } catch (e) {
      throw new Error("non-JSON response: " + text.slice(0, 200));
    }
    if (!r.ok) {
      throw new Error(body.detail || body.error || "HTTP " + r.status);
    }
    return body;
  }

  async function previewFile(file) {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file, file.name);
    submitSummary.textContent = "Parsing " + file.name + "…";
    try {
      const body = await postForm("/encounters/upload/preview", fd);
      if (body.error) {
        previewRows = [];
        renderPreview();
        previewSummary.textContent = body.error;
        return;
      }
      applyPreviewRows(body.rows, body.filename);
    } catch (err) {
      previewRows = [];
      renderPreview();
      previewSummary.textContent = "Preview failed: " + err.message;
    }
  }

  async function pastePreview(form) {
    const payload = {};
    const fd = new FormData(form);
    fd.forEach((v, k) => {
      if (v != null && v !== "") payload[k] = v;
    });
    // Normalise CPT codes: split the comma-separated string into an
    // array the server can read directly.
    if (payload.cpt_codes && typeof payload.cpt_codes === "string") {
      payload.cpt_codes_list = payload.cpt_codes
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    }
    try {
      const body = await postForm(
        "/encounters/upload/paste",
        (() => {
          const out = new FormData();
          out.append("payload", JSON.stringify(payload));
          return out;
        })()
      );
      applyPreviewRows(body.rows, body.filename);
    } catch (err) {
      previewRows = [];
      renderPreview();
      previewSummary.textContent = "Paste preview failed: " + err.message;
    }
  }

  async function submitAccepted() {
    if (btnSubmit.disabled) return;
    const fd = new FormData();
    fd.append("payload", JSON.stringify({ rows: previewRows }));
    btnSubmit.disabled = true;
    submitSummary.textContent = "Submitting…";
    try {
      const body = await postForm("/encounters/upload/submit", fd);
      submitSummary.textContent =
        `${body.jobs.length} accepted, ${body.rejected.length} rejected.`;
      if (body.jobs && body.jobs.length) {
        jobsPanel.hidden = false;
        body.jobs.forEach(addJobRow);
        body.jobs.forEach((j) => startPolling(j.job_id));
      }
    } catch (err) {
      submitSummary.textContent = "Submit failed: " + err.message;
      btnSubmit.disabled = false;
    }
  }

  function addJobRow(job) {
    const li = jobTpl.content.firstElementChild.cloneNode(true);
    li.dataset.jobId = job.job_id;
    li.querySelector(".job-row__id").textContent = job.job_id;
    li.querySelector(".job-row__enc").textContent = job.encounter_id || "";
    const statusEl = li.querySelector(".job-row__status");
    statusEl.textContent = "queued";
    jobList.appendChild(li);
  }

  function updateJobRow(job) {
    const li = jobList.querySelector('[data-job-id="' + job.job_id + '"]');
    if (!li) return;
    const statusEl = li.querySelector(".job-row__status");
    statusEl.textContent = job.status;
    statusEl.classList.remove("badge--clean", "badge--flag");
    if (job.status === "done") statusEl.classList.add("badge--clean");
    if (job.status === "failed") statusEl.classList.add("badge--flag");
    if (job.error) {
      const err = document.createElement("div");
      err.className = "cell-error";
      err.textContent = job.error;
      li.appendChild(err);
    }
  }

  function startPolling(jobId) {
    if (pollers[jobId]) return;
    pollers[jobId] = setInterval(async () => {
      try {
        const r = await fetch("/encounters/upload/jobs/" + jobId);
        if (r.status === 404) {
          clearInterval(pollers[jobId]);
          delete pollers[jobId];
          return;
        }
        const body = await r.json();
        updateJobRow(body);
        if (body.status === "done" || body.status === "failed") {
          clearInterval(pollers[jobId]);
          delete pollers[jobId];
        }
      } catch (e) {
        // Network blip; keep polling.
      }
    }, 1000);
  }

  async function uploadNote(file) {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file, file.name);
    noteStatus.textContent = "Uploading " + file.name + "…";
    try {
      const r = await fetch("/encounters/upload/notes", { method: "POST", body: fd });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "HTTP " + r.status);
      noteStatus.textContent =
        "Stored " + body.filename + " (" + body.size_bytes + " bytes) as " +
        body.note_id + " — OCR " + body.ocr_status + ".";
    } catch (err) {
      noteStatus.textContent = "Note upload failed: " + err.message;
    }
  }

  // ---- wire up ---------------------------------------------------------

  tabs.forEach((t) => {
    t.addEventListener("click", () => showTab(t.dataset.target));
  });

  dropzones.forEach((dz) => {
    const kind = dz.dataset.kind;
    const input = dz.querySelector('input[type="file"]');
    const fileLabel = dz.querySelector(".dropzone__filename");
    dz.addEventListener("dragover", (e) => {
      e.preventDefault();
      dz.classList.add("dropzone--over");
    });
    dz.addEventListener("dragleave", () => dz.classList.remove("dropzone--over"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("dropzone--over");
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (!f) return;
      fileLabel.textContent = f.name;
      if (kind === "note") {
        uploadNote(f);
      } else {
        previewFile(f);
      }
    });
    dz.addEventListener("click", (e) => {
      // Forward click on the label to the hidden input.
      if (e.target !== input) input.click();
    });
    if (input) {
      input.addEventListener("change", () => {
        const f = input.files && input.files[0];
        if (!f) return;
        fileLabel.textContent = f.name;
        if (kind === "note") {
          uploadNote(f);
        } else {
          previewFile(f);
        }
      });
    }
  });

  if (btnPastePreview) {
    btnPastePreview.addEventListener("click", () => pastePreview(pasteForm));
  }
  if (btnSubmit) btnSubmit.addEventListener("click", submitAccepted);
  if (btnClear) {
    btnClear.addEventListener("click", () => {
      previewRows = [];
      renderPreview();
      submitSummary.textContent = "";
    });
  }

  // initial tab
  showTab("tab-837p");
})();
