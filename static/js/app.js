/* Framecraft Studio — frontend (vanilla JS, no build step) */
"use strict";

const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => [...(el || document).querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

const S = { settings: null, projects: [], project: null, tab: "studio", knowTab: "mastery" };
const STAGES = [["brief","Brief"],["approval","Approval"],["images","Images"],["videos","Videos"],["edit","Final Edit"]];
const STAGE_ORDER = ["brief","approval","images","videos","edit","done"];
const SECTIONS = [
  ["storyboard","Storyboard"],
  ["script_cta","Script & CTA Split"],
  ["shotlist","Shot List"],
  ["characters","Character Minting"],
  ["environments","Setting / Environment Mint"],
];
const STYLES = ["ugc","claymation","pixar","cinematic","anime","noir","paper"];
const RATIOS = [["16:9","Landscape (16:9)"],["9:16","Vertical (9:16)"],["1:1","Square (1:1)"],["4:5","Portrait (4:5)"]];

/* ── api helpers ── */
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({ ok:false, error:`HTTP ${r.status}` }));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}
const post = (path, body) => api(path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body||{})});

function toast(msg, isErr) {
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), 5200);
}
function busy(on, label) {
  $("#busy").hidden = !on;
  if (label) $("#busy-label").textContent = label;
}
const asset = (rel, v) => `/api/projects/${S.project.id}/asset?rel=${encodeURIComponent(rel)}&v=${v||1}`;
const mb = (b) => (b/1048576).toFixed(1) + " MB";

function mdlite(md) {
  let x = esc(md||"");
  x = x.replace(/```([\s\S]*?)```/g, (_,c) => `<pre><code>${c.trim()}</code></pre>`);
  x = x.replace(/^###### (.*)$/gm,"<h4>$1</h4>").replace(/^### (.*)$/gm,"<h3>$1</h3>")
       .replace(/^## (.*)$/gm,"<h2>$1</h2>").replace(/^# (.*)$/gm,"<h1>$1</h1>");
  x = x.replace(/^> (.*)$/gm,"<blockquote>$1</blockquote>");
  x = x.replace(/^---+$/gm,"<hr>");
  x = x.replace(/\*\*([^*]+)\*\*/g,"<b>$1</b>").replace(/\*([^*\n]+)\*/g,"<i>$1</i>").replace(/`([^`]+)`/g,"<code>$1</code>");
  x = x.replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  x = x.replace(/(?:^|\n)((?:- .*(?:\n|$))+)/g, (_,block) => "\n<ul>"+block.trim().split("\n").map(l=>`<li>${l.replace(/^- /,"")}</li>`).join("")+"</ul>");
  x = x.split(/\n{2,}/).map(p => (/^<(h\d|ul|pre|blockquote|hr)/.test(p.trim()) ? p : `<p>${p.replace(/\n/g,"<br>")}</p>`)).join("\n");
  return x;
}

/* ── boot ── */
init();
async function init() {
  document.documentElement.dataset.theme = localStorage.getItem("fc-theme") || "light";
  bind();
  try {
    const st = await api("/api/state");
    S.settings = st.settings;
    S.projects = st.projects;
    renderTop();
    if (st.projects.length) await openProject(st.projects[0].id);
    else renderAll();
  } catch(e) { toast(e.message, true); }
}

function bind() {
  $("#tabs").addEventListener("click", e => {
    const b = e.target.closest("[data-tab]");
    if (!b) return;
    S.tab = b.dataset.tab;
    renderAll();
  });
  $("#mode-pill").addEventListener("click", async e => {
    const b = e.target.closest("[data-mode]");
    if (!b || b.dataset.mode === S.settings.mode) return;
    try {
      const r = await post("/api/mode", {mode: b.dataset.mode});
      S.settings = r.settings;
      renderTop();
      toast(r.mode === "live" ? "Live mode armed." : "Demo mode — local python engines.");
    } catch(err) { toast(err.message, true); }
  });
  $("#theme-btn").addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = t;
    localStorage.setItem("fc-theme", t);
  });

  document.addEventListener("click", onAction);

  /* ── checkbox handlers — the ONLY place we update project state from checkboxes ── */
  document.addEventListener("change", async e => {
    const el = e.target;

    /* Approval section checkboxes (client-side only — no API call) */
    if (el.matches(".appr-cb")) {
      const card = el.closest(".seccard");
      const box  = $(".revbox", card);
      if (box) box.hidden = el.checked;
      card.classList.toggle("approved", el.checked);
      updateDecideBtn();
      return;
    }

    /* Image approve toggles — POST then update state then re-render */
    if (el.matches("[data-mark]") && S.project) {
      const sid = el.dataset.mark;
      const wantApproved = el.checked;
      try {
        const r = await post(`/api/projects/${S.project.id}/images/mark`, {scene_id: sid, approved: wantApproved});
        S.project = r.project;           // <-- update state BEFORE re-render
      } catch(x) {
        el.checked = !wantApproved;      // revert the checkbox if the API rejects
        toast(x.message, true);
      }
      renderStage();
      return;
    }

    /* Video clip approve toggles */
    if (el.matches("[data-vmark]") && S.project) {
      const sid = el.dataset.vmark;
      const wantApproved = el.checked;
      try {
        const r = await post(`/api/projects/${S.project.id}/videos/mark`, {scene_id: sid, approved: wantApproved});
        S.project = r.project;
      } catch(x) {
        el.checked = !wantApproved;
        toast(x.message, true);
      }
      renderStage();
      return;
    }
  });
}

/* ── action router ── */
async function onAction(e) {
  const a = e.target.closest("[data-act]");
  if (!a) return;
  const act = a.dataset.act;
  const pid = S.project && S.project.id;
  const go = async (label, fn) => {
    busy(true, label);
    try { await fn(); }
    catch(err) { toast(err.message, true); }
    finally { busy(false); }
  };

  switch(act) {

    case "newproj":
      $("#newproj").hidden = !$("#newproj").hidden;
      break;

    case "createproj":
      await go("Creating project…", async () => {
        const r = await post("/api/projects", {name: $("#np-name").value.trim(), folder: $("#np-folder").value.trim()});
        S.projects.unshift({id:r.project.id, name:r.project.name, folder:r.project.folder, stage:"brief"});
        S.project = r.project;
        toast(`Project "${r.project.name}" created.`);
        renderAll();
      });
      break;

    case "selectproj":
      await openProject(a.dataset.id);
      break;

    /* ── stage navigation — no longer blocked for "future" steps ── */
    case "stage":
      await go("Navigating…", async () => {
        const r = await post(`/api/projects/${pid}/stage`, {stage: a.dataset.stage});
        S.project = r.project;
        renderAll();
      });
      break;

    case "process":
      await go("LLM is reading Mastery.md + Workflow.md and building the package…", async () => {
        const fd = new FormData();
        fd.set("brief",          $("#brief-in").value);
        fd.set("style",          $("#style-in").value);
        fd.set("aspect_ratio",   $("#aspect-ratio") ? $("#aspect-ratio").value : "16:9");
        fd.set("reference_note", $("#ref-note").value);
        const rf = $("#ref-file").files[0];
        if (rf) fd.set("reference", rf);
        const vf = $("#voice-file") && $("#voice-file").files[0];
        if (vf) fd.set("voiceover", vf);
        const r = await api(`/api/projects/${pid}/process`, {method:"POST", body:fd});
        S.project = r.project;
        toast(r.project.brief.transcript
          ? `Creative package ready — transcript source: ${r.project.brief.transcript_source}.`
          : "Creative package ready for approval.");
        renderAll();
      });
      break;

    /* Separate voiceover upload + transcribe (no full process) */
    case "process-voice":
      await go("Transcribing voiceover…", async () => {
        const vf = $("#voice-file") && $("#voice-file").files[0];
        if (!vf) { toast("Choose an audio file first.", true); return; }
        const fd = new FormData();
        fd.set("voiceover", vf);
        const r = await api(`/api/projects/${pid}/voiceover`, {method:"POST", body:fd});
        S.project = r.project;
        toast(`Transcript ready — source: ${r.source}`);
        renderStage();
      });
      break;

    case "style-chip":
      $("#style-in").value = a.dataset.v;
      break;

    case "decide":
      await go("Applying decision…", async () => {
        const approvals = {}, comments = {};
        SECTIONS.forEach(([k]) => {
          approvals[k] = $(`.appr-cb[data-sec="${k}"]`).checked;
          comments[k]  = $(`.revbox[data-sec="${k}"] textarea`)?.value || "";
        });
        const r = await post(`/api/projects/${pid}/package/decision`, {approvals, comments});
        S.project = r.project;
        if (r.next === "images") {
          toast("Package approved — generating scene images…");
          busy(true, "Writing image prompts & generating scenes (IDs locked in Scene Marker)…");
          const g = await post(`/api/projects/${pid}/images/generate`);
          S.project = g.project;
          busy(false);
        } else if (r.next === "revised-approved") {
          toast(`Approved package revised to v${r.project.package.version}.`);
        } else if (r.next === "noop") {
          toast("Already approved. Uncheck a section and add a comment to revise.");
        } else {
          toast(`Revision v${r.project.package.version} applied.`);
        }
        renderAll();
      });
      break;

    case "genimg":
      await go("Writing image prompts & generating scenes…", async () => {
        const g = await post(`/api/projects/${pid}/images/generate`);
        S.project = g.project;
        renderStage();
      });
      break;

    case "imrev":
      await go(`Revising ${a.dataset.sid}…`, async () => {
        const ta = $(`textarea[data-imc="${a.dataset.sid}"]`);
        if (!ta || !ta.value.trim()) { toast("Add a revision comment first.", true); return; }
        const r = await post(`/api/projects/${pid}/images/${a.dataset.sid}/revise`, {comment: ta.value});
        S.project = r.project;
        renderStage();
      });
      break;

    case "imrr":
      await go(`Rerolling ${a.dataset.sid}…`, async () => {
        const r = await post(`/api/projects/${pid}/images/${a.dataset.sid}/reroll`);
        S.project = r.project;
        renderStage();
      });
      break;

    case "imgdone":
      await go("Locking images…", async () => {
        const r = await post(`/api/projects/${pid}/images/decision`, {});
        S.project = r.project;
        toast("Images locked — ready for video generation.");
        renderAll();
      });
      break;

    case "vidnext":
      await go("LLM is writing motion prompts & generating 4 clips…", async () => {
        const r = await post(`/api/projects/${pid}/videos/next`);
        S.project = r.project;
        renderStage();
      });
      break;

    case "vidbappr":
      await go("Approving batch…", async () => {
        const r = await post(`/api/projects/${pid}/videos/batch/${a.dataset.b}/approve`);
        S.project = r.project;
        toast(r.all_done ? "All clips approved — delivery time." : `Batch approved. ${r.remaining} scene(s) left.`);
        renderStage();
      });
      break;

    case "vidrev":
      await go(`Revising clip ${a.dataset.sid}…`, async () => {
        const ta = $(`textarea[data-vidc="${a.dataset.sid}"]`);
        if (!ta || !ta.value.trim()) { toast("Add a revision comment first.", true); return; }
        const r = await post(`/api/projects/${pid}/videos/${a.dataset.sid}/revise`, {comment: ta.value});
        S.project = r.project;
        renderStage();
      });
      break;

    case "vidrr":
      await go(`Rerolling clip ${a.dataset.sid}…`, async () => {
        const r = await post(`/api/projects/${pid}/videos/${a.dataset.sid}/reroll`);
        S.project = r.project;
        renderStage();
      });
      break;

    case "choice":
      await go("Saving delivery choice…", async () => {
        const r = await post(`/api/projects/${pid}/videos/choice`, {self: a.dataset.self === "1"});
        S.project = r.project;
        renderAll();
      });
      break;

    case "editbegin":
      await go("Running final edit via remotion skill…", async () => {
        const r = await post(`/api/projects/${pid}/edit/begin`);
        S.project = r.project;
        toast("Final edit rendered.");
        renderStage();
      });
      break;

    case "upload": {
      const files = $("#learn-files").files;
      if (!files.length) { toast("Choose one or more videos first.", true); break; }
      await go(`Uploading ${files.length} video(s)…`, async () => {
        const fd = new FormData();
        [...files].forEach(f => fd.append("files", f));
        await api("/api/learn/upload", {method:"POST", body:fd});
        toast("Saved to local learn folder.");
        renderAll();
      });
      break;
    }

    case "analyse":
      await go("Analyzing why this ad worked & updating Mastery.md…", async () => {
        const r = await post("/api/learn/process", {file: a.dataset.f});
        toast(`Mastery.md consolidated — ${r.mastery_sources} source(s) total.`);
        renderAll();
      });
      break;

    case "knowtab":
      S.knowTab = a.dataset.k;
      renderAll();
      break;

    case "savesettings":
      await go("Saving settings…", async () => {
        const body = collectSettings();
        const r = await post("/api/settings", body);
        S.settings = r.settings;
        renderTop();
        toast(r.settings.live_ready ? "Saved — Live mode is now available." : "Saved. (Live still locked until LLM+Image+Video keys are set.)");
        renderAll();
      });
      break;
  }
}

function updateDecideBtn() {
  const btn = $('[data-act="decide"]');
  if (!btn) return;
  const approvedOnce = !!(S.project && S.project.package_approved);
  const un = SECTIONS.filter(([k]) => !$(`.appr-cb[data-sec="${k}"]`)?.checked).length;
  if (approvedOnce) {
    // After first approval: show "Apply revisions" only when something is unchecked
    if (un === 0) {
      btn.hidden = true;
    } else {
      btn.hidden = false;
      btn.textContent = `Apply revisions (${un} section${un > 1 ? "s" : ""})`;
      btn.className = "btn";
    }
  } else {
    btn.hidden = false;
    btn.textContent = un === 0
      ? "Approve All — Continue to Image Generation"
      : `Send Revisions (${un} section${un > 1 ? "s" : ""} to fix)`;
    btn.className = un === 0 ? "btn btn-primary" : "btn";
  }
}

async function openProject(id) {
  try {
    const r = await api(`/api/projects/${id}`);
    S.project = r.project;
  } catch(e) { toast(e.message, true); }
  renderAll();
}

/* ── top bar ── */
function renderTop() {
  $$("#tabs .tab").forEach(b => b.classList.toggle("on", b.dataset.tab === S.tab));
  const seg = $("#mode-pill");
  $$("button", seg).forEach(b => {
    b.classList.toggle("on", b.dataset.mode === S.settings.mode);
    if (b.dataset.mode === "live") {
      b.classList.toggle("off", !S.settings.live_ready);
      b.title = S.settings.live_ready ? "Live providers armed" : "Locked — set API keys in Settings";
    }
  });
}

function renderAll() {
  renderTop();
  ["studio","learn","knowledge","settings"].forEach(v => { $(`#view-${v}`).hidden = S.tab !== v; });
  if (S.tab === "studio")    renderStudio();
  if (S.tab === "learn")     renderLearn();
  if (S.tab === "knowledge") renderKnowledge();
  if (S.tab === "settings")  renderSettings();
}

/* ── studio ── */
function renderStudio() {
  const v = $("#view-studio");
  const p = S.project;
  const list = S.projects.map(x => `<option value="${x.id}" ${p && p.id === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("");
  v.innerHTML = `
    <div class="card">
      <div class="row">
        <h2 style="margin:0;font:400 26px 'Instrument Serif'">Production Studio</h2>
        <div class="right">
          <select class="inp" id="proj-sel">${list || "<option>No projects</option>"}</select>
          <button class="btn btn-ghost btn-sm" data-act="selectproj" data-id="${p ? p.id : ""}" onclick="this.dataset.id=document.getElementById('proj-sel').value">Open</button>
          <button class="btn btn-primary btn-sm" data-act="newproj">+ New ad</button>
        </div>
      </div>
      <div id="newproj" class="notecard" hidden style="margin-top:14px">
        <div class="grid2">
          <div><label class="lbl">Name of the ad</label><input class="inp" id="np-name" placeholder="e.g. BrightBottle — Summer UGC 30s"></div>
          <div><label class="lbl">Project folder <span class="mut">(blank → ${esc(S.settings.projects_root)}/&lt;name&gt;)</span></label><input class="inp" id="np-folder" placeholder="/Users/you/ads/brightbottle"></div>
        </div>
        <div class="row" style="margin-top:12px">
          <button class="btn btn-primary" data-act="createproj">Create project</button>
          <span class="mut small">Everything (brief, prompts, assets, scene marker, EDL) is saved inside this folder.</span>
        </div>
      </div>
    </div>
    <div id="stage-host">${p ? "" : '<div class="card mut">Create your first ad project to begin.</div>'}</div>`;
  if (p) { renderStepper(); renderStage(); }
}

function renderStepper() {
  const p = S.project;
  const stageIdx = STAGE_ORDER.indexOf(p.stage);
  const currentIdx = stageIdx < 0 ? 0 : stageIdx;

  $("#stage-host").innerHTML = `
    <div class="stepper">${STAGES.map(([k, l], i) => {
      const isPast    = i < currentIdx;
      const isCurrent = i === currentIdx;
      const isFuture  = i > currentIdx;
      return `<div class="step ${isPast?"done":""} ${isCurrent?"on":""} ${isFuture?"future":""}" data-act="stage" data-stage="${k}">
        <span class="n">${isPast?"✓":i+1}</span>${l}${k==="edit"&&p.edit?.self?" (you)":""}
      </div>`;
    }).join("")}</div>
    <div id="panel"></div>`;
}

/* ── sidebar ── */
function renderSidebar() {
  const p = S.project;
  if (!p || !p.package) return "";
  let totalT = 0;
  const clips = {};
  p.videos.batches.forEach(b => b.clips.forEach(c => clips[c.scene_id] = c));
  const items = p.package.scenes.map((s, i) => {
    const start = totalT;
    totalT += s.duration;
    const fmt = t => `${Math.floor(t/60)}:${(t%60|0).toString().padStart(2,"0")}`;
    const clip = clips[s.id];
    const img  = (p.images||[]).find(im => im.scene_id === s.id);
    return `
      <div class="marker-item">
        <div class="row" style="gap:6px">
          <span class="time">${fmt(start)} – ${fmt(totalT)}</span>
          <span class="sc-num">${s.id}</span>
          ${img  ? `<span class="tag" style="margin-left:auto">${img.asset_id}</span>` : ""}
          ${clip ? `<span class="tag">${clip.asset_id}</span>` : ""}
        </div>
        <div class="vo">"${esc(s.vo)}"</div>
        <div class="motion">🎬 ${esc(s.visual.split(";")[0].replace(/^PATTERN-INTERRUPT — /i,""))}</div>
        ${img && clip && img.rev > (clip.source_image_rev||1)
          ? `<div class="sync-warn" style="margin-top:4px;padding:4px 8px;font-size:11px">⚠ video stale vs keyframe r${img.rev}</div>`
          : ""}
      </div>`;
  }).join("");

  return `
    <aside class="prod-sidebar">
      <h4 class="sec" style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M3 12h18"/><path d="M17 3v18"/>
        </svg>
        Scene Markers
      </h4>
      ${items}
    </aside>`;
}

/* ── stage renderer ── */
function renderStage() {
  const p = S.project, host = $("#panel");
  if (!host || !p) return;

  const wrapLayout = html => `
    <div class="prod-container">
      <div class="prod-main">${html}</div>
      ${renderSidebar()}
    </div>`;

  switch(p.stage) {
    case "brief":    host.innerHTML = vBrief(p); break;
    case "approval": host.innerHTML = vApproval(p); updateDecideBtn(); break;
    case "images":   host.innerHTML = wrapLayout(vImages(p)); break;
    case "videos":   host.innerHTML = wrapLayout(vVideos(p)); break;
    case "edit":     host.innerHTML = wrapLayout(`<div class="card mut">Loading final-edit status…</div>`); loadEdit(p); break;
    case "done":     host.innerHTML = vDone(p); break;
  }
}

/* ── Brief ── */
function vBrief(p) {
  const ar = p.brief.aspect_ratio || "16:9";
  const vo = p.brief.voiceover;
  const tx = p.brief.transcript || "";
  return `
  <div class="card">
    <div class="card-h"><h3>${esc(p.name)}</h3><span class="chip">${esc(p.folder)}</span><span class="mut">mode: ${S.settings.mode}</span></div>

    <label class="lbl">Script / Ad Brief</label>
    <textarea class="inp" id="brief-in" style="min-height:130px" placeholder="Paste script or ad brief here. Or upload voiceover below — the app will transcribe it for you.">${esc(p.brief.text||"")}</textarea>

    <div class="grid2" style="margin-top:10px">
      <div>
        <label class="lbl">Style</label>
        <input class="inp" id="style-in" value="${esc(p.brief.style||"ugc")}" placeholder="UGC, Claymation, Pixar, Noir…">
        <div class="row" style="flex-wrap:wrap;margin-top:7px">${STYLES.map(s=>`<button class="chip" data-act="style-chip" data-v="${s}">${s}</button>`).join("")}</div>
      </div>
      <div>
        <label class="lbl">Aspect Ratio</label>
        <div class="row" style="flex-wrap:wrap;gap:7px;margin-top:2px" id="aspect-btns">
          ${RATIOS.map(([val,lbl])=>`<button class="chip ${ar===val?"acc":""}" style="cursor:pointer" onclick="document.getElementById('aspect-ratio').value='${val}';document.querySelectorAll('#aspect-btns .chip').forEach(b=>b.classList.remove('acc'));this.classList.add('acc')">${lbl}</button>`).join("")}
        </div>
        <input type="hidden" id="aspect-ratio" value="${ar}">
        <label class="lbl" style="margin-top:10px">Reference (optional)</label>
        <input class="inp" id="ref-file" type="file" accept="video/*,image/*,.pdf">
        <input class="inp" id="ref-note" style="margin-top:7px" placeholder="What about it should the LLM study?" value="${esc(p.brief.reference_note||"")}">
        ${p.brief.reference ? `<div class="mut small" style="margin-top:4px">On file: ${esc(p.brief.reference.orig)}</div>` : ""}
      </div>
    </div>

    <div class="grid2" style="margin-top:14px">
      <div>
        <label class="lbl">Voiceover / Audio (optional)</label>
        <input class="inp" id="voice-file" type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg">
        <div class="row" style="margin-top:8px;gap:8px">
          <button class="btn btn-ghost btn-sm" data-act="process-voice">Transcribe only ↺</button>
          <span class="mut small" style="font-size:12px">Transcribes without running the full LLM package process.</span>
        </div>
        ${vo ? `<div class="mut small" style="margin-top:4px">On file: ${esc(vo.orig)}</div>` : ""}
      </div>
      <div>
        <label class="lbl">Transcript ${p.brief.transcript_source ? `<span class="mut">· ${esc(p.brief.transcript_source)}</span>` : ""}</label>
        <textarea class="inp" id="transcript-preview" readonly style="min-height:90px;opacity:.9">${esc(tx || "No transcript yet — upload a voiceover and click Transcribe, or it will auto-transcribe when you Process.")}</textarea>
        ${tx ? `<div class="mut small" style="margin-top:4px">This transcript is included with the LLM brief for caption timing.</div>` : ""}
      </div>
    </div>

    <div class="row" style="margin-top:18px">
      <button class="btn btn-primary" data-act="process">Process →</button>
      <span class="mut small">Sends brief + transcript + reference + style + aspect ratio to the LLM with <b>Mastery.md & Workflow.md</b>.</span>
    </div>
    ${p.package ? `<div class="notecard" style="margin-top:14px">Package v${p.package.version} exists (<span class="mono">${esc(p.package.engine)}</span>). Re-processing resets images &amp; videos — go back to <b>Approval</b> to revise without losing assets.</div>` : ""}
  </div>`;
}

/* ── Approval ── */
function secContent(k, pkg) {
  if (k === "storyboard") return pkg.scenes.map(s => `
    <div class="strow">
      <span class="tag">${s.id}</span>
      <span class="chip acc">${s.beat}</span>
      <div><b>${esc(s.title)}</b> <span class="mut">· ${s.duration}s</span><br>${esc(s.visual)}<br><span class="vo">VO: "${esc(s.vo)}"</span></div>
    </div>`).join("");
  if (k === "script_cta") return `
    ${pkg.scenes.map(s=>`<div class="strow"><span class="tag">${s.id}</span><span class="mut small">${s.duration}s</span><span class="vo">"${esc(s.vo)}"</span></div>`).join("")}
    <div class="notecard" style="margin-top:10px"><b>CTA:</b> "${esc(pkg.cta.line)}"<br>
      <span class="mono">on-screen: ${esc(pkg.cta.on_screen)} · timing: ${esc(pkg.cta.timing)} · formula: ${esc(pkg.cta.formula)}</span></div>`;
  if (k === "shotlist") return pkg.shots.map(s=>`
    <div class="shotrow"><span class="tag">${s.scene_id}</span><span>${esc(s.shot)}</span><span class="mut">${esc(s.lens)}</span><span>${esc(s.movement)}</span><span class="mut small">${esc(s.notes)}</span></div>`).join("");
  if (k === "characters") return `<div class="grid2">${pkg.characters.map(c=>`
    <div class="seccard"><div class="sechead"><span class="tag">${c.token}</span><h4>${esc(c.name)}</h4><span class="chip">${esc(c.role)}</span></div>
      <div class="mono small mut">${esc(c.mint_prompt)}</div></div>`).join("")}</div>`;
  if (k === "environments") return `<div class="grid2">${pkg.environments.map(e=>`
    <div class="seccard"><div class="sechead"><span class="tag">${e.token}</span><h4>${esc(e.name)}</h4></div>
      <div class="mono small mut">${esc(e.mint_prompt)}</div></div>`).join("")}</div>`;
  return "";
}

function vApproval(p) {
  const pkg = p.package;
  if (!pkg) return `<div class="card mut">No package yet — go back to Brief and click Process.</div>`;
  const approvedOnce = !!p.package_approved;
  const revs = (pkg.revisions_log||[]).map(r=>`<span class="chip warn">v${r.version}: ${esc(Object.values(r.changes||{}).flat()[0]||"revised")}</span>`).join(" ");
  return `
  <div class="card">
    <div class="card-h">
      <h3>For Approval</h3>
      <span class="chip acc">${esc(pkg.engine)}</span>
      <span class="chip">v${pkg.version}</span>
      <span class="chip">${esc(pkg.style)}</span>
      <span class="mut">${pkg.scenes.length} scenes · ${pkg.target_duration}s · ${esc(p.brief.aspect_ratio||"16:9")}</span>
    </div>
    <div class="notecard" style="margin-bottom:14px">
      <b>Mastery.md applied:</b>${pkg.mastery_applied.map(m=>`<br>· ${esc(m)}`).join("")}
      <br><span class="mut">${(pkg.notes||[]).map(esc).join(" · ")}</span>
    </div>
    ${approvedOnce ? `<div class="notecard" style="margin-bottom:12px;border-color:var(--ok)">
      <b>✓ Already approved.</b> All sections are checked. To revise a specific section, uncheck it, add a comment, then click Apply revisions.
    </div>` : ""}
    ${revs ? `<div class="row" style="flex-wrap:wrap;margin-bottom:12px">${revs}</div>` : ""}
    ${SECTIONS.map(([k, label]) => {
      const checked = approvedOnce ? true : !!p.approvals?.[k];
      return `
      <div class="seccard ${checked?"approved":""}">
        <div class="sechead">
          <h4>${label}</h4>
          <label class="appr-label"><input type="checkbox" class="appr-cb" data-sec="${k}" ${checked?"checked":""}> Approve</label>
        </div>
        ${secContent(k, pkg)}
        <div class="revbox" data-sec="${k}" ${checked?"hidden":""}>
          <textarea class="inp" placeholder="Revision comment for "${label}" — be specific about what to change…"></textarea>
        </div>
      </div>`;
    }).join("")}
    <div class="row" style="margin-top:4px">
      <button class="btn" data-act="decide">Send Revisions</button>
      <span class="mut small">${approvedOnce
        ? "Uncheck any section above to enable the revision button."
        : "Check all sections to see the Approve All button."}</span>
    </div>
  </div>`;
}

/* ── Images ── */
function markerStrip(p) {
  const clips = {};
  p.videos.batches.forEach(b => b.clips.forEach(c => clips[c.scene_id] = c));
  return `<div class="marker">${p.images.map(i => {
    const clip  = clips[i.scene_id];
    const stale = clip && i.rev > (clip.source_image_rev||1);
    return `<span class="chip ${i.approved?"ok":""} ${stale?"warn":""}">${i.scene_id} · <span class="tag">${i.asset_id}</span>${clip?` → <span class="tag">${clip.asset_id}</span>`:""}${stale?" · video stale":""}</span>`;
  }).join("")}</div>`;
}

function vImages(p) {
  if (!p.images.length) return `
    <div class="card">
      <div class="card-h"><h3>Image Generation</h3><span class="mut">Package v${p.package.version} approved</span></div>
      <p class="mut">LLM writes one image prompt per scene from the approved package. Asset IDs (<span class="tag">IMG-SC-…</span>) are locked in the Scene Marker — none are ever lost.</p>
      <button class="btn btn-primary" data-act="genimg">Generate all scene images</button>
    </div>`;
  const allOk = p.images.every(i => i.approved);
  const clips  = {}; p.videos.batches.forEach(b => b.clips.forEach(c => clips[c.scene_id] = c));
  return `
  <div class="card">
    <div class="card-h">
      <h3>Scene Marker — Images</h3>
      <span class="mut">${p.images.filter(i=>i.approved).length}/${p.images.length} approved · LLM QC per frame</span>
    </div>
    ${markerStrip(p)}
    <div class="scenegrid">${p.images.map(i => {
      const clip  = clips[i.scene_id];
      const stale = clip && i.rev > (clip.source_image_rev||1);
      return `
      <div class="scene-card ${i.approved?"approved":""}">
        <img src="${asset(i.file, i.rev)}" alt="${i.scene_id}" loading="lazy">
        <div class="scene-body">
          <div class="row">
            <span class="tag">${i.asset_id}</span>
            <span class="chip ${i.qc&&i.qc.status==="pass"?"ok":"warn"}">QC: ${i.qc?i.qc.status:"—"}</span>
            <span class="mut small right">${esc(i.scene_id)}</span>
          </div>
          ${stale ? `<div class="sync-warn">VIDEO CLIP STALE <span class="sync-warn-tag">Videos tab flagged</span><br>
            <span style="font-size:11px;font-weight:400">Keyframe is newer (r${i.rev}) than generated clip (r${clip.source_image_rev||1}). Reroll that clip in the Videos tab.</span></div>` : ""}
          ${i.qc ? `<details class="fold"><summary>LLM QC review</summary><ul style="margin:4px 0 0">${i.qc.notes.map(n=>`<li>${esc(n)}</li>`).join("")}</ul></details>` : ""}
          <details class="fold"><summary>Prompt</summary><pre>${esc(i.prompt)}</pre></details>
          <div class="scene-controls">
            <label><input type="checkbox" data-mark="${i.scene_id}" ${i.approved?"checked":""}> Approve</label>
            <button class="btn btn-ghost btn-sm" data-act="imrr" data-sid="${i.scene_id}">Reroll</button>
          </div>
          <details class="fold"><summary>Revise with comment</summary>
            <textarea class="inp" data-imc="${i.scene_id}" placeholder="e.g. make it night-time, move subject left…"></textarea>
            <button class="btn btn-sm" style="margin-top:6px" data-act="imrev" data-sid="${i.scene_id}">Apply revision → new rev</button>
          </details>
        </div>
      </div>`;
    }).join("")}</div>
    <div class="row" style="margin-top:18px">
      <a class="btn btn-ghost" href="/api/projects/${p.id}/download/images.zip">↓ Download all stills</a>
      <div class="right">
        <button class="btn btn-primary" data-act="imgdone" ${allOk?"":"disabled"}>Proceed to Video Generation →</button>
      </div>
    </div>
    ${allOk ? "" : `<div class="mut small" style="margin-top:8px">Every frame must be approved before proceeding — revise or reroll until it looks right.</div>`}
  </div>`;
}

/* ── Videos ── */
function vVideos(p) {
  const scenes    = p.package.scenes;
  const made      = p.videos.batches.flatMap(b => b.clips.map(c => c.scene_id));
  const remaining = scenes.filter(s => !made.includes(s.id)).map(s => s.id);
  const lastB     = p.videos.batches[p.videos.batches.length-1];
  const imgs      = {}; p.images.forEach(i => imgs[i.scene_id] = i);

  let body = "";
  if (!p.videos.batches.length) {
    body = `<div class="card">
      <div class="card-h"><h3>Video Generation</h3><span class="mut">batches of 4 · approve / reroll / revise per clip</span></div>
      <p class="mut">Motion prompts are written from each approved still. Scenes generate 4 at a time — approve a batch to unlock the next one.</p>
      <button class="btn btn-primary" data-act="vidnext">Generate batch 1 — ${remaining.slice(0,4).join(", ")}</button>
    </div>`;
  }

  body += p.videos.batches.map((b, bi) => `
    <div class="card">
      <div class="card-h">
        <h3>Batch ${bi+1}</h3>
        <span class="mut">${b.clips.map(c=>c.scene_id).join(" · ")}</span>
        <span class="chip ${b.approved?"ok":"warn"}">${b.approved?"approved":"in review"}</span>
        <span class="right"><a class="btn btn-ghost btn-sm" href="/api/projects/${p.id}/download/batch-${bi}.zip">↓ Download batch</a></span>
      </div>
      <div class="scenegrid">${b.clips.map(c => {
        const img = imgs[c.scene_id];
        const outOfSync = img && img.rev > (c.source_image_rev||1);
        return `
        <div class="scene-card ${c.approved?"approved":""}">
          <img src="${asset(c.file, c.rev)}" alt="${c.scene_id}" loading="lazy">
          <div class="scene-body">
            <div class="row"><span class="tag">${c.asset_id}</span><span class="chip">${esc(c.move||"")}</span><span class="mut small right">${c.scene_id}</span></div>
            ${outOfSync ? `<div class="sync-warn">KEYFRAME CHANGED <span class="sync-warn-tag">Out of Sync</span><br>
              <span style="font-size:11px;font-weight:400">Base image revised (r${c.source_image_rev} → r${img.rev}). Reroll this clip to match the new keyframe.</span></div>` : ""}
            <details class="fold"><summary>Motion prompt</summary><pre>${esc(c.motion)}</pre></details>
            ${c.history.length ? `<details class="fold"><summary>Revision history</summary><ul>${c.history.map(h=>`<li class="small">r${h.rev}: ${esc(h.comment)}</li>`).join("")}</ul></details>` : ""}
            <div class="scene-controls">
              <label><input type="checkbox" data-vmark="${c.scene_id}" ${c.approved?"checked":""}> Approve</label>
              <button class="btn btn-ghost btn-sm" data-act="vidrr" data-sid="${c.scene_id}">Reroll</button>
            </div>
            <details class="fold"><summary>Revise with comment</summary>
              <textarea class="inp" data-vidc="${c.scene_id}" placeholder="e.g. slower push-in; smile earlier…"></textarea>
              <button class="btn btn-sm" style="margin-top:6px" data-act="vidrev" data-sid="${c.scene_id}">Apply revision → new rev</button>
            </details>
          </div>
        </div>`;
      }).join("")}</div>
      ${b.approved ? "" : `
      <div class="row" style="margin-top:14px">
        <button class="btn btn-primary" data-act="vidbappr" data-b="${bi}" ${b.clips.every(c=>c.approved)?"":"disabled"}>Approve batch ${bi+1}</button>
        <span class="mut small">Enable once all clips in this batch are checked.</span>
      </div>`}
    </div>`).join("");

  if (p.videos.batches.length && lastB && lastB.approved && !p.videos.done && remaining.length) {
    body += `<div class="card row">
      <div><b>Batch approved.</b> <span class="mut">${remaining.length} scene(s) remaining.</span></div>
      <div class="right"><button class="btn btn-primary" data-act="vidnext">Proceed → next 4 (${remaining.slice(0,4).join(", ")})</button></div>
    </div>`;
  }
  if (p.videos.done && p.edit.self === null) {
    body += `<div class="card">
      <div class="card-h"><h3>All clips approved 🎉</h3></div>
      <p class="mut">You can download everything and edit yourself, or let the AI cut the final video using the Scene Marker + Mastery.md.</p>
      <div class="row" style="flex-wrap:wrap">
        <a class="btn" href="/api/projects/${p.id}/download/clips.zip">↓ Download all clips + scene marker</a>
        <button class="btn btn-primary" data-act="choice" data-self="0">AI makes the final edit →</button>
        <button class="btn btn-ghost" data-act="choice" data-self="1">I'll edit it myself</button>
      </div>
    </div>`;
  }
  return body || `<div class="card mut">…</div>`;
}

/* ── Final Edit ── */
async function loadEdit(p) {
  try {
    const r = await api(`/api/projects/${p.id}/edit/status`);
    const host = $(".prod-main", $("#panel"));
    if (!host || S.project.id !== p.id) return;
    const sk      = r.skills;
    const skillOk = sk.installed;
    const res     = (p.edit||{}).result;
    const clips   = {}; p.videos.batches.forEach(b => b.clips.forEach(c => clips[c.scene_id] = c));
    const staleFinal = res?.source_clip_revs
      ? Object.keys(res.source_clip_revs).filter(sid => (clips[sid]?.rev||0) > (res.source_clip_revs[sid]||0))
      : [];

    host.innerHTML = `
      <div class="card">
        <div class="card-h"><h3>Final Edit</h3>
          <span class="chip ${skillOk?"ok":"warn"}">${skillOk?"remotion skill installed":"skill missing"}</span>
        </div>
        ${!skillOk ? `<div class="notecard"><b>Required skill not found:</b> <code>skills/claude-remotion-skill</code>
          <pre>${sk.install.join("\n")}</pre>
          <span class="mut small">Demo mode simulates the render; Live mode requires the skill.</span></div>` : ""}
        ${staleFinal.length ? `<div class="sync-warn">FINAL EDIT STALE <span class="sync-warn-tag">Re-run needed</span><br>
          <span style="font-size:11px;font-weight:400">Scenes with newer clips since last edit: ${staleFinal.join(", ")}.</span></div>` : ""}
        <h4 class="sec" style="margin-top:16px">Scene Marker → editor</h4>
        <div class="marker">${r.marker.map(m => {
          const stale = staleFinal.includes(m.scene_id);
          return `<span class="chip ${m.clip_approved?"ok":""} ${stale?"warn":""}">${m.scene_id} · <span class="tag">${m.clip||"—"}</span> · ${m.duration}s · ${m.beat}${stale?" · stale":""}</span>`;
        }).join("")}</div>
        <div class="row" style="margin-top:10px">
          <button class="btn btn-primary" data-act="editbegin" ${!skillOk&&S.settings.mode==="live"?"disabled":""}>${staleFinal.length?"Re-run Final Edit":"Begin Final Edit"}</button>
          <span class="mut small">Follows Mastery.md pacing; assets mapped 1:1 via the Scene Marker.</span>
        </div>
      </div>
      ${res ? `
      <div class="card">
        <div class="card-h"><h3>Final cut</h3><span class="chip ok">${esc(res.engine)}</span><span class="mut">${esc(res.finished)}</span></div>
        ${res.preview ? `<img src="${asset(res.preview, Date.now())}" style="width:100%;max-width:640px;border-radius:12px;border:1px solid var(--line)">` : ""}
        <div class="row" style="margin-top:14px;flex-wrap:wrap">
          <a class="btn btn-primary" href="/api/projects/${p.id}/download/final.zip">↓ Download final package</a>
          ${res.edl       ? `<a class="btn btn-ghost" href="${asset(res.edl)}"          target="_blank">edl.json</a>` : ""}
          ${res.notes     ? `<a class="btn btn-ghost" href="${asset(res.notes)}"         target="_blank">FINAL_EDIT_NOTES.md</a>` : ""}
          ${res.scene_marker ? `<a class="btn btn-ghost" href="${asset(res.scene_marker)}" target="_blank">scene_marker.json</a>` : ""}
        </div>
      </div>` : ""}`;
  } catch(e) {
    const host = $(".prod-main", $("#panel"));
    if (host) host.innerHTML = `<div class="card mut">${esc(e.message)}</div>`;
  }
}

/* ── Done ── */
function vDone(p) {
  return `<div class="card">
    <div class="card-h"><h3>Delivered</h3><span class="chip ok">${p.edit.self?"hand-off to you":"AI edit complete"}</span></div>
    <p class="mut">All assets are in <span class="mono">${esc(p.folder)}</span> — prompts, revisions, scene marker, EDL included.</p>
    <div class="row" style="flex-wrap:wrap">
      <a class="btn" href="/api/projects/${p.id}/download/clips.zip">↓ Clips + scene marker</a>
      <a class="btn" href="/api/projects/${p.id}/download/images.zip">↓ Stills</a>
      ${p.edit.result ? `<a class="btn btn-primary" href="/api/projects/${p.id}/download/final.zip">↓ Final edit package</a>` : ""}
    </div>
  </div>`;
}

/* ── Learn ── */
async function renderLearn() {
  const v = $("#view-learn");
  v.innerHTML = `<div class="card mut">Loading uploads…</div>`;
  let items = [];
  try { items = (await api("/api/learn/list")).items; } catch(e) { toast(e.message, true); }
  v.innerHTML = `
    <div class="card">
      <div class="card-h"><h3>Learn from winning ads</h3><span class="mut">stored in <span class="mono">./uploads</span></span></div>
      <div class="drop">
        <input type="file" id="learn-files" class="inp" multiple accept="video/*" style="max-width:420px;margin:0 auto 12px">
        <br><button class="btn btn-primary" data-act="upload">Upload</button>
        <div class="mut small" style="margin-top:8px">Then hit <b>Process</b> — the LLM analyzes why each ad worked and rewrites <b>Mastery.md</b>.</div>
      </div>
    </div>
    <div class="card kblist">
      <div class="card-h"><h3>Library</h3><span class="mut">${items.filter(i=>i.processed).length}/${items.length} processed</span></div>
      ${items.length ? items.map(i => `
        <div class="row" style="align-items:flex-start">
          <div class="grow">
            <b>${esc(i.file)}</b> <span class="mut small">· ${mb(i.size)} · ${esc((i.uploaded||"").replace("T"," "))}</span>
            <span class="chip ${i.processed?"ok":""}" style="margin-left:8px">${i.processed?"processed":"unprocessed"}</span>
            ${i.insights ? `<details class="fold" style="margin-top:8px"><summary>Analysis</summary>
              <div style="font-size:13px;margin-top:6px">
                <b>Hook:</b> ${esc(i.insights.hook)} · <b>Pacing:</b> ${esc(i.insights.pacing)} · <b>CTA:</b> ${esc(i.insights.cta)}<br>
                <b>Structure:</b> ${esc(i.insights.structure)}
                <ul>${(i.insights.why_worked||[]).map(w=>`<li>${esc(w)}</li>`).join("")}</ul>
                <b>Steal this:</b><ul>${(i.insights.steal||[]).map(w=>`<li>${esc(w)}</li>`).join("")}</ul>
              </div></details>` : ""}
          </div>
          <div class="row">
            <a class="btn btn-ghost btn-sm" href="/uploads/${encodeURIComponent(i.file)}" target="_blank">View</a>
            <button class="btn btn-sm ${i.processed?"":"btn-primary"}" data-act="analyse" data-f="${esc(i.file)}">${i.processed?"Re-process":"Process"}</button>
          </div>
        </div>`).join("") : '<div class="mut">Nothing uploaded yet.</div>'}
    </div>`;
}

/* ── Knowledge ── */
async function renderKnowledge() {
  const v = $("#view-knowledge");
  v.innerHTML = `<div class="card mut">Loading…</div>`;
  try {
    const which = S.knowTab;
    const d = await api(`/api/knowledge/${which}`);
    const h = which === "mastery" ? (await api("/api/knowledge/mastery/history")).versions : [];
    v.innerHTML = `
      <div class="card">
        <div class="card-h"><h3>Knowledge</h3>
          <div class="tabs" style="margin:0">
            <button class="tab ${which==="mastery"?"on":""}" data-act="knowtab" data-k="mastery">Mastery.md</button>
            <button class="tab ${which==="workflow"?"on":""}" data-act="knowtab" data-k="workflow">Workflow.md</button>
          </div>
          <span class="mut right">${d.name} ${which==="mastery"?`· ${h.length} archived version(s)`:""}</span>
        </div>
        <div class="notecard small">The LLM <b>reads Mastery.md before every creative call</b> and <b>updates it after every analysis</b>. Old versions are archived in <code>knowledge/history/</code>.</div>
        <div class="md" style="margin-top:14px">${mdlite(d.text)}</div>
      </div>`;
  } catch(e) { v.innerHTML = `<div class="card mut">${esc(e.message)}</div>`; }
}

/* ── Settings ── */
const PROV = {
  llm:   ["local","script","openai","anthropic","gemini","opencode"],
  image: ["local","stability","picsart","huggingface","openai","higgsfield"],
  video: ["local","huggingface","higgsfield","heygen"],
  voice: ["local","elevenlabs"],
};

// Stability engine presets
const STABILITY_MODELS = [
  ["stable-diffusion-xl-1024-v1-0", "SDXL 1.0 (recommended)"]
];

// PicsArt model presets
const PICSART_MODELS = [
  ["urn:air:fluxai:model:fluxai:flux-2-pro@1",   "FLUX 2 Pro (default)"],
  ["urn:air:fluxai:model:fluxai:flux-1-pro@1",   "FLUX 1 Pro"],
  ["urn:air:fluxai:model:fluxai:flux-2-ultra@1", "FLUX 2 Ultra"],
  ["urn:air:sd:model:stability:sdxl@1",           "Stable Diffusion XL"],
];

// LLM model presets per provider
const LLM_MODELS = {
  openai:    [["gpt-4o","GPT-4o"],["gpt-4o-mini","GPT-4o Mini"],["gpt-4.1","GPT-4.1"],["gpt-4.1-mini","GPT-4.1 Mini"],["gpt-4.1-nano","GPT-4.1 Nano"],["o3","o3"],["o4-mini","o4 Mini"]],
  anthropic: [["claude-sonnet-4-5","Claude Sonnet 4.5"],["claude-sonnet-4-20250514","Claude Sonnet 4"],["claude-haiku-4-20250414","Claude Haiku 4"],["claude-3-5-haiku-20241022","Claude 3.5 Haiku"]],
  gemini:    [["gemini-2.5-flash","Gemini 2.5 Flash"],["gemini-2.5-pro","Gemini 2.5 Pro"],["gemini-2.0-flash","Gemini 2.0 Flash"],["gemini-2.0-flash-lite","Gemini 2.0 Flash Lite"]],
  opencode:  [],  // free-form — user types the model name
};

// HF image model presets
const HF_IMAGE_MODELS = [
  ["black-forest-labs/FLUX.1-dev",     "FLUX.1 Dev (default)"],
  ["black-forest-labs/FLUX.1-schnell", "FLUX.1 Schnell (fast)"],
  ["stabilityai/stable-diffusion-xl-base-1.0", "SDXL Base 1.0"],
];

// HF video model presets
const HF_VIDEO_MODELS = [
  ["MiniMaxAI/MiniMax-H3", "MiniMax H3 (recommended)"],
  ["Wan-AI/Wan2.1-I2V-14B-720P", "Wan 2.1 I2V 14B"],
  ["Wan-AI/Wan2.1-I2V-14B-480P", "Wan 2.1 I2V 14B 480P"],
];
const LOCAL_INFO = {
  llm:   `<b>Local python LLM (demo brain).</b> Builds packages, applies revisions, writes prompts, analyzes uploads. No API key needed.<br><br><b>OpenCode / Custom?</b> Uses OpenAI API format. Set Base URL to your local server (e.g. LM Studio, vLLM) or OpenRouter.<br><br><b>Custom script?</b> Pick <b>script</b> and set the path. Contract: JSON on stdin → <code>{"text":…}</code> on stdout.`,
  image: `<b>Local placeholder painter</b> (Pillow). Draws a styled captioned frame per scene, deterministic per revision.<br><br><b>Stability?</b> Uses SDXL 1.0 via Stability's REST API. Cheap test defaults: <code>samples=1</code>, <code>steps=10</code>, <code>cfg_scale=5</code>.<br><br><b>PicsArt?</b> Uses GenAI Text2Image (async, with automatic polling). Paste your <code>paat-…</code> key. Default model: FLUX 2 Pro.<br><br><b>HuggingFace?</b> Uses Inference Client <code>text_to_image</code>. Default model: <code>black-forest-labs/FLUX.1-dev</code>.`,
  video: `<b>Local GIF renderer</b>. Animates the approved still (pan/push/tilt + sweep). Reroll = new seeded move.<br><br><b>HuggingFace?</b> Uses the Inference Client (<code>image_to_video</code>). Default model: <code>MiniMaxAI/MiniMax-H3</code>. Generates real mp4 clips from your approved keyframes + motion prompt.`,
  voice: `<b>Local STT helper</b> (<code>local_programs/transcribe_voiceover.py</code>). Uses Whisper if installed, otherwise sidecar .txt or filename fallback. Add ElevenLabs in Live mode for synthesis.`,
};

function _modelField(provName, p) {
  // For LLM providers with known model lists → dropdown
  if (provName === "llm" && LLM_MODELS[p.kind] && LLM_MODELS[p.kind].length) {
    return `<select class="inp" data-k="model" style="width:auto">
      ${LLM_MODELS[p.kind].map(([v,l])=>`<option value="${v}" ${(p.model||"")=== v?"selected":""}>${l}</option>`).join("")}
      <option value="_custom" ${LLM_MODELS[p.kind].some(([v])=>v===p.model)?"":"selected"}>Custom…</option>
    </select>
    <input class="inp" data-k="model_custom" style="margin-top:6px;${LLM_MODELS[p.kind].some(([v])=>v===p.model) || !p.model?"display:none":""}" value="${esc(LLM_MODELS[p.kind].some(([v])=>v===p.model)?"":p.model)}" placeholder="Type custom model ID…">`;
  }
  // For HF image → dropdown
  if (provName === "image" && p.kind === "huggingface") {
    return `<select class="inp" data-k="model" style="width:auto">
      ${HF_IMAGE_MODELS.map(([v,l])=>`<option value="${v}" ${(p.model||"")=== v?"selected":""}>${l}</option>`).join("")}
    </select>`;
  }
  // For HF video → dropdown
  if (provName === "video" && p.kind === "huggingface") {
    return `<select class="inp" data-k="model" style="width:auto">
      ${HF_VIDEO_MODELS.map(([v,l])=>`<option value="${v}" ${(p.model||"")=== v?"selected":""}>${l}</option>`).join("")}
    </select>`;
  }
  // Fallback: plain text input
  return `<input class="inp" data-k="model" value="${esc(p.model||"")}">`;
}

function provBlock(name, p, ready) {
  const kinds    = PROV[name];
  const isLocal  = p.kind === "local";
  const needsKey = !isLocal && p.kind !== "script";
  return `
  <div class="seccard" data-prov="${name}">
    <div class="sechead">
      <h4 style="text-transform:capitalize">${name}</h4>
      <span class="chip ${ready[name]?"ok":""}">${ready[name]?"ready":isLocal?"local":"not configured"}</span>
      <select class="inp" data-k="kind" style="margin-left:auto">${kinds.map(k=>`<option ${p.kind===k?"selected":""}>${k}</option>`).join("")}</select>
    </div>
    <div data-when="key" ${needsKey?"":"hidden"}>
      <div class="grid2">
        <div><label class="lbl">API key ${p.has_key?`<span class="mut">(saved ${esc(p.key_tail)})</span>`:""}</label>
          <input class="inp" data-k="api_key" type="password" placeholder="${p.has_key?"leave blank to keep": (p.kind==="opencode"?"optional for local":"paste key…")}"></div>
        
        <div data-when="generic_model" ${(!["picsart","stability"].includes(p.kind) || name !== "image") ? "" : "hidden"}>
          <label class="lbl">Model</label>
          ${_modelField(name, p)}
        </div>

        ${name==="voice"?`<div><label class="lbl">Voice ID</label><input class="inp" data-k="voice_id" value="${esc(p.voice_id||"")}"></div>`:""}
      </div>
      <div data-when="base_url" ${p.kind==="opencode"?"":"hidden"} style="margin-top:10px">
        <label class="lbl">Base URL</label>
        <input class="inp" data-k="base_url" value="${esc(p.base_url||"")}" placeholder="e.g. http://localhost:11434/v1 or https://openrouter.ai/api/v1">
      </div>
      ${name==="image"&&p.kind==="higgsfield"?`<label class="row small" style="margin-top:10px"><input type="checkbox" data-k="use_mcp" ${p.use_mcp?"checked":""}> &nbsp;Higgsfield MCP — <b>always inject @elements</b> in image prompts</label>`:""}

      <div data-when="hf_provider" ${p.kind==="huggingface"?"":"hidden"} style="margin-top:10px">
        <label class="lbl">HF Inference Provider</label>
        <select class="inp" data-k="hf_provider" style="width:auto">
          ${["auto","fal","wavespeed","replicate","together"].map(v=>`<option ${(p.hf_provider||"auto")===v?"selected":""}>${v}</option>`).join("")}
        </select>
        <span class="mut small" style="margin-left:8px"><code>auto</code> = HF picks the fastest available provider</span>
      </div>

      <div data-when="stability_opts" ${p.kind==="stability"&&name==="image"?"":"hidden"} style="margin-top:10px">
        <label class="lbl">Stability engine
          <span class="mut" style="text-transform:none;letter-spacing:0"> — bearer API key</span>
        </label>
        <select class="inp" data-k="model" style="width:auto">
          ${(typeof STABILITY_MODELS !== "undefined" ? STABILITY_MODELS : []).map(([v,l])=>`<option value="${v}" ${(p.model||"")===v?"selected":""}>${l}</option>`).join("")}
        </select>
        <div class="grid2" style="margin-top:10px">
          <div>
            <label class="lbl">Steps <span class="mut" style="text-transform:none;letter-spacing:0">(cheap test default = 10)</span></label>
            <input class="inp" data-k="stability_steps" type="number" min="10" max="50" step="1" value="${esc(p.stability_steps ?? 10)}">
          </div>
          <div>
            <label class="lbl">CFG Scale</label>
            <input class="inp" data-k="stability_cfg_scale" type="number" min="0" max="35" step="0.5" value="${esc(p.stability_cfg_scale ?? 5)}">
          </div>
        </div>
        <div class="notecard small" style="margin-top:8px">
          For your 25-credit test run, the app defaults to <b>1 sample</b>, <b>10 steps</b>, and maps your Brief aspect ratio to the nearest official SDXL size.
        </div>
      </div>

      <div data-when="picsart_model" ${p.kind==="picsart"&&name==="image"?"":"hidden"} style="margin-top:10px">
        <label class="lbl">PicsArt model
          <span class="mut" style="text-transform:none;letter-spacing:0"> — key header: <code>X-Picsart-API-Key: paat-…</code></span>
        </label>
        <select class="inp" data-k="model" style="width:auto">
          ${(typeof PICSART_MODELS !== "undefined" ? PICSART_MODELS : []).map(([v,l])=>`<option value="${v}" ${(p.model||"")===v?"selected":""}>${l}</option>`).join("")}
        </select>
        <div class="notecard small" style="margin-top:8px">
          Images are generated asynchronously — the app polls until the image is ready (up to 5 min).
          Width × Height comes from the <b>aspect ratio</b> you set in Brief.
        </div>
      </div>
    </div>
    <div data-when="script" ${p.kind==="script"?"":"hidden"} style="margin-top:10px">
      <label class="lbl">Path to your python script</label>
      <input class="inp" data-k="local_script" value="${esc(p.local_script||"")}" placeholder="/path/to/my_brain.py">
    </div>
    <div class="notecard small" data-when="local" ${isLocal?"":"hidden"} style="margin-top:10px">${LOCAL_INFO[name]}</div>
  </div>`;
}

function renderSettings() {
  const s = S.settings, v = $("#view-settings");
  v.innerHTML = `
  <div class="card">
    <div class="card-h"><h3>Settings</h3>
      <span class="chip ${s.mode==="live"?"ok":"acc"}">mode: ${s.mode}</span>
      <span class="mut right">${s.live_ready?"Live unlocked":"Live locked — needs LLM + Image + Video keys"}</span>
    </div>
    <label class="lbl">Default projects folder</label>
    <input class="inp" id="set-root" value="${esc(s.projects_root)}">
  </div>
  <div class="card">
    <div class="card-h"><h3>Providers</h3><span class="mut">keys stored in config.json — never sent anywhere except the provider</span></div>
    ${["llm","image","video","voice"].map(n=>provBlock(n, s.providers[n], s.ready)).join("")}
    <div class="row" style="margin-top:14px">
      <button class="btn btn-primary" data-act="savesettings">Save settings</button>
      <span class="mut small">Choosing <b>local</b> shows install notes inline above.</span>
    </div>
  </div>`;
  $$(".seccard[data-prov] select[data-k='kind']", v).forEach(sel => sel.addEventListener("change", () => {
    const card = sel.closest(".seccard"), k = sel.value;
    const provName = card.dataset.prov;
    $(`[data-when="key"]`,    card).hidden = k === "local" || k === "script";
    $(`[data-when="script"]`, card).hidden = k !== "script";
    $(`[data-when="local"]`,  card).hidden = k !== "local";
    const burl = $(`[data-when="base_url"]`, card);
    if (burl) burl.hidden = k !== "opencode";
    const hfp = $(`[data-when="hf_provider"]`, card);
    if (hfp) hfp.hidden = k !== "huggingface";
    const stb = $(`[data-when="stability_opts"]`, card);
    if (stb) stb.hidden = !(k === "stability" && provName === "image");
    const pap = $(`[data-when="picsart_model"]`, card);
    if (pap) pap.hidden = !(k === "picsart" && provName === "image");
    const genm = $(`[data-when="generic_model"]`, card);
    if (genm) genm.hidden = (["picsart","stability"].includes(k) && provName === "image");
  }));

  // LLM model dropdown: show/hide custom text field when "Custom…" is selected
  $$("select[data-k='model']", v).forEach(sel => {
    sel.addEventListener("change", () => {
      const custom = sel.closest(".seccard")?.querySelector("input[data-k='model_custom']");
      if (custom) custom.style.display = sel.value === "_custom" ? "" : "none";
    });
  });
}

function collectSettings() {
  const body = { projects_root: $("#set-root").value.trim(), providers: {} };
  $$(".seccard[data-prov]").forEach(card => {
    const name = card.dataset.prov, out = {};
    $$("[data-k]", card).forEach(el => {
      // Skip fields inside blocks that are currently hidden for this provider kind
      const block = el.closest("[data-when]");
      if (block && block.hidden) return;
      // Skip the custom model helper field — handled below
      if (el.dataset.k === "model_custom") return;
      if (el.dataset.k === "api_key" && !el.value) return;
      out[el.dataset.k] = el.type === "checkbox" ? el.checked : el.value;
    });
    // If model is "_custom", use the custom text field value instead
    if (out.model === "_custom") {
      const custom = card.querySelector("input[data-k='model_custom']");
      out.model = custom ? custom.value.trim() : "";
    }
    body.providers[name] = out;
  });
  return body;
}
