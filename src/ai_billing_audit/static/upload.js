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

  // 25 MiB matches the QA-confirmed client-side limit documented in
  // the upload-UI task. The server enforces a stricter 10 MiB cap
  // (see api._MAX_UPLOAD_BYTES); the client check is the friendly
  // pre-flight that surfaces the error before any bytes leave the
  // browser. Anything between 10 MiB and 25 MiB will still be
  // rejected by the server with a 413 — the error message there is
  // intentionally the same string.
  const MAX_CLIENT_UPLOAD_BYTES = 25 * 1024 * 1024;
  const MAX_SERVER_UPLOAD_BYTES = 10 * 1024 * 1024;

  function formatBytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KiB";
    return (n / (1024 * 1024)).toFixed(2) + " MiB";
  }

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

  // Per-dropzone error region. We create it lazily so the template
  // stays clean and we don't ship a placeholder div for every
  // dropzone. The error is a small <p> with class
  // ``dropzone__error`` that the CSS can style red and italic.
  function getOrCreateErrorRegion(dz) {
    let err = dz.querySelector(".dropzone__error");
    if (!err) {
      err = document.createElement("p");
      err.className = "dropzone__error muted small";
      err.setAttribute("role", "alert");
      // Insert after the dropzone label, before the next sibling.
      dz.parentNode.insertBefore(err, dz.nextSibling);
    }
    return err;
  }
  function clearError(dz) {
    const err = dz.querySelector(".dropzone__error");
    if (err) err.remove();
  }
  function setError(dz, msg) {
    const err = getOrCreateErrorRegion(dz);
    err.textContent = msg;
  }

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
        // Poll each job and, on completion, redirect to the
        // encounter detail page. The first job's encounter_id
        // wins — for a single-file upload the redirect happens
        // once; for a bulk ZIP the user lands on the first
        // encounter and the rest stay visible in the
        // recent-uploads list with their own "View encounter"
        // links.
        let redirected = false;
        body.jobs.forEach((j) => {
          startPolling(j.job_id, function (finalJob) {
            if (redirected) return;
            if (finalJob.status === "done" && finalJob.encounter_id) {
              redirected = true;
              submitSummary.textContent =
                "Audit complete — opening " + finalJob.encounter_id + "…";
              setTimeout(function () {
                location.href =
                  "/encounters/" + encodeURIComponent(finalJob.encounter_id);
              }, 400);
            }
          });
        });
      }
    } catch (err) {
      submitSummary.textContent = "Submit failed: " + err.message;
      btnSubmit.disabled = false;
    }
  }

  function addJobRow(job) {
    const li = jobTpl.content.firstElementChild.cloneNode(true);
    li.dataset.jobId = job.job_id;
    li.dataset.encounterId = job.encounter_id || "";
    li.querySelector(".job-row__id").textContent = job.job_id;
    // The "View encounter" link is hidden until the job is done
    // AND the encounter_id is a non-empty string. The link uses
    // the spec URL /encounters/{id} (plural), which the live
    // dashboard serves via the encounter_detail_plural handler
    // added alongside /encounter/{id}.
    const enc = job.encounter_id || "";
    const encLink = li.querySelector(".job-row__view");
    if (encLink) {
      encLink.href = "/encounters/" + encodeURIComponent(enc);
      encLink.hidden = true;
    }
    li.querySelector(".job-row__enc").textContent = enc;
    const statusEl = li.querySelector(".job-row__status");
    statusEl.textContent = "queued";
    // Initialise the progress bar at 0% so the bar exists in the
    // DOM from the first render. updateJobRow() updates the width
    // and aria-valuenow on every poll tick.
    const bar = li.querySelector(".job-row__bar");
    if (bar) {
      bar.style.width = "0%";
      bar.setAttribute("aria-valuenow", "0");
    }
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
    // Drive the progress bar from the poll response. The server
    // sends both ``stage`` (text) and ``progress`` (0-100 number);
    // the bar prefers the number and falls back to the status
    // string when the number is missing.
    const bar = li.querySelector(".job-row__bar");
    if (bar) {
      const pct = Number.isFinite(job.progress) ? job.progress : null;
      const width =
        pct !== null
          ? Math.max(0, Math.min(100, pct))
          : job.status === "done"
            ? 100
            : job.status === "failed"
              ? 0
              : job.status === "running"
                ? 15
                : 0;
      bar.style.width = width + "%";
      bar.setAttribute("aria-valuenow", String(width));
    }
    // The "View encounter" link becomes visible once the job is
    // done and we have an encounter_id to link to.
    if (job.status === "done") {
      const encLink = li.querySelector(".job-row__view");
      const eid = job.encounter_id || li.dataset.encounterId;
      if (encLink && eid) {
        encLink.href = "/encounters/" + encodeURIComponent(eid);
        encLink.hidden = false;
      }
    }
    if (job.error) {
      const err = document.createElement("div");
      err.className = "cell-error";
      err.textContent = job.error;
      li.appendChild(err);
    }
  }

  function startPolling(jobId, onDone) {
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
          if (typeof onDone === "function") onDone(body);
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
      handleSelectedFile(dz, kind, input, fileLabel, f);
    });
    dz.addEventListener("click", (e) => {
      // Forward click on the label to the hidden input.
      if (e.target !== input) input.click();
    });
    if (input) {
      input.addEventListener("change", () => {
        const f = input.files && input.files[0];
        if (!f) return;
        handleSelectedFile(dz, kind, input, fileLabel, f);
      });
    }
  });

  // Centralised handler for "user picked/dropped a file" so the
  // drag/drop and the click-to-pick paths stay in lock-step.
  // Enforces the 25 MiB client limit on the 837P/ZIP/note paths,
  // shows the file name + size under the dropzone, and dispatches
  // to the right upload handler.
  function handleSelectedFile(dz, kind, input, fileLabel, f) {
    clearError(dz);
    // 25 MiB cap, expressed as the QA-confirmed string. Anything
    // over this is rejected before any bytes are sent.
    if (f.size > MAX_CLIENT_UPLOAD_BYTES) {
      fileLabel.textContent = "";
      // Clear the input so the user can re-pick without unselecting
      // first; otherwise the browser keeps the file in the picker
      // and the change event won't refire on re-selection of the
      // same file.
      if (input) input.value = "";
      setError(
        dz,
        f.name + " is " + formatBytes(f.size) +
          ", which is over the 25 MiB limit. Pick a smaller file."
      );
      return;
    }
    // File name + size under the dropzone. The size is the user's
    // first visual confirmation that the file they just picked is
    // actually the one they meant to pick — particularly useful
    // when the upload takes a few seconds to start.
    fileLabel.textContent = f.name + " (" + formatBytes(f.size) + ")";
    if (kind === "note") {
      uploadNote(f);
    } else {
      previewFile(f);
    }
  }

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
