/* NOVA Omniverse studio UI. No framework, no build step. Untrusted text (scripts, issues,
   profile names) is always inserted with textContent, never innerHTML. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const store = {
  get(k, d) { try { const v = localStorage.getItem("nova." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("nova." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};
const state = {
  system: null, profiles: [], activeVoice: store.get("voice", ""), mode: store.get("mode", "natural"),
  scenes: store.get("scenes", []), lastAnalysis: null,
};

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false)
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
}
const clear = (el) => { el.replaceChildren(); return el; };

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 5000);
}

// ---------- API ----------
function authHeaders() {
  const key = store.get("key", "");
  return key ? { Authorization: "Bearer " + key } : {};
}
function withToken(url) {
  const key = store.get("key", "");
  return key ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(key) : url;
}
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: { ...authHeaders() } };
  if (opts.json !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.json); }
  if (opts.form) init.body = opts.form;
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((e) => e.msg).join("; ") : `HTTP ${res.status}`);
  }
  return data;
}
async function busy(btn, fn) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Working…";
  try { return await fn(); } catch (e) { toast(e.message); throw e; } finally { btn.disabled = false; btn.textContent = label; }
}

// ---------- routing ----------
const ROUTES = ["dashboard", "clone", "library", "intel", "enhance", "director", "studio", "projects", "settings"];
function route() {
  const name = (location.hash.match(/^#\/(\w+)/) || [])[1];
  const view = ROUTES.includes(name) ? name : "dashboard";
  for (const s of $$("[data-view]")) s.hidden = s.dataset.view !== view;
  for (const a of $$("#nav a")) a.toggleAttribute("aria-current", a.dataset.route === view) && a.setAttribute("aria-current", "page");
  const current = $(`#nav a[data-route="${view}"]`);
  if (current) current.scrollIntoView({ block: "nearest", inline: "nearest" });
  document.title = `${current ? current.textContent : "Dashboard"} · NOVA Omniverse`;
  if (view === "library") renderLibrary();
  if (view === "studio") renderStudio();
  if (view === "projects") renderProjects();
  if (view === "dashboard") renderDashboard();
  if (view === "settings") $("#sys-out").textContent = JSON.stringify(state.system, null, 2);
  $("#main").focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// ---------- shared script ----------
const scriptEl = () => $("#script");
function getScript() { return scriptEl().value.trim(); }
function setScript(text) { scriptEl().value = text; store.set("script", text); }

// ---------- system / dashboard ----------
async function loadSystem() {
  try {
    state.system = await api("/api/system");
    state.profiles = await api("/api/profiles");
  } catch (e) {
    toast(e.message.includes("API key") ? "This server needs an API key: add it in Settings." : e.message);
  }
  fillEmotionSelects();
  updateActiveVoice();
}
function fillEmotionSelects() {
  const emotions = state.system ? state.system.emotions : [];
  for (const sel of [$("#dir-emotion"), $("#studio-emotion")]) {
    if (sel.options.length > 1) continue;
    for (const e of emotions) sel.append(h("option", { value: e }, cap(e)));
  }
  const ps = $("#design-preset");
  if (state.system && !ps.options.length) {
    for (const p of state.system.presets) ps.append(h("option", { value: p.id }, p.name));
    applyPreset();
  }
}
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
function renderDashboard() {
  const s = state.system;
  const engines = s ? s.engines : [];
  const stats = [
    [state.profiles.filter((p) => p.kind !== "designed").length, "cloned voices"],
    [state.profiles.filter((p) => p.kind === "designed").length, "designed voices"],
    [engines.filter((e) => e.available).length, "engines ready"],
    [s && s.llm.configured ? "On" : "Off", "local LLM"],
  ];
  clear($("#dash-stats")).append(...stats.map(([v, l]) => h("div", { class: "card stat" }, h("b", {}, v), h("span", {}, l))));
  clear($("#dash-engines")).append(...engines.map((e) => h("div", { class: "card engine" },
    h("h3", {}, e.name), h("p", {}, h("span", { class: "pill " + (e.available ? "ok" : "bad") }, e.available ? "Ready" : "Not installed")),
    h("p", { class: "hint" }, "Controls: " + (Object.entries(e.controls).filter(([, on]) => on).map(([k]) => k.replace("_", " ")).join(", ") || "rate only")),
  )));
}
function updateActiveVoice() {
  const p = state.profiles.find((x) => x.id === state.activeVoice);
  if (!p && state.activeVoice) { state.activeVoice = ""; store.set("voice", ""); }
  $("#active-voice").textContent = p ? p.name : "None selected";
}

// ---------- cloning ----------
let recorder = null, recChunks = [], recBlob = null, recTimer = null;
function setupClone() {
  for (const b of $$("#clone-form .seg-btn")) b.addEventListener("click", () => {
    $$("#clone-form .seg-btn").forEach((x) => x.classList.toggle("on", x === b));
    $$("[data-src-pane]").forEach((p) => { p.hidden = p.dataset.srcPane !== b.dataset.src; });
  });
  $("#rec-btn").addEventListener("click", toggleRecording);
  $("#clone-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target, status = $("#clone-status");
    const fd = new FormData(f);
    const recording = !$('[data-src-pane="record"]').hidden;
    fd.delete("audio");
    if (recording) {
      if (!recBlob) return toast("Record a sample first.");
      fd.append("audio", recBlob, "recording.webm");
    } else {
      const file = $("#clone-file").files[0];
      if (!file) return toast("Choose an audio file.");
      fd.append("audio", file);
    }
    fd.set("consent_confirmed", f.consent_confirmed.checked ? "true" : "false");
    status.className = "status";
    status.textContent = "Analysing voice…";
    try {
      const p = await busy(f.querySelector("[type=submit]"), () => api("/api/profiles", { method: "POST", form: fd }));
      status.textContent = `Profile “${p.name}” created and encrypted.`;
      showAnalysis(p.voice);
      state.profiles = await api("/api/profiles");
      selectVoice(p.id);
    } catch (e) { status.className = "status err"; status.textContent = e.message; }
  });
  const df = $("#design-form");
  $("#design-preset").addEventListener("change", applyPreset);
  for (const r of $$("input[type=range]", df)) r.addEventListener("input", () => syncOutput(r));
  df.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const body = { preset: df.preset.value };
    if (df.name.value.trim()) body.name = df.name.value.trim();
    for (const r of $$("input[type=range]", df)) body[r.name] = Number(r.value);
    try {
      const p = await busy(df.querySelector("[type=submit]"), () => api("/api/profiles/design", { method: "POST", json: body }));
      $("#design-status").textContent = `Designed voice “${p.name}” saved. Preview it in the Voice Library.`;
      state.profiles = await api("/api/profiles");
      selectVoice(p.id);
    } catch (e) { $("#design-status").textContent = e.message; }
  });
}
const PRESET_VALUES = {
  "soft-young-indonesian-woman": { pitch_hz: 228, range_semitones: 7, formant_scale_hz: 1440, breathiness: 0.32, rate: 0.94, volume_db: -2 },
  "warm-indonesian-man": { pitch_hz: 118, range_semitones: 6, formant_scale_hz: 1180, breathiness: 0.1, rate: 0.96, volume_db: 0 },
  "clear-english-narrator": { pitch_hz: 205, range_semitones: 6.5, formant_scale_hz: 1410, breathiness: 0.12, rate: 0.98, volume_db: 0 },
};
function applyPreset() {
  const v = PRESET_VALUES[$("#design-preset").value];
  if (!v) return;
  for (const [k, val] of Object.entries(v)) { const r = $(`#design-form [name=${k}]`); r.value = val; syncOutput(r); }
}
function syncOutput(r) {
  const o = r.closest("label").querySelector("output");
  if (o) o.textContent = r.value;
}
async function toggleRecording() {
  const btn = $("#rec-btn");
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  if (!navigator.mediaDevices || !window.MediaRecorder) return toast("Recording is not supported in this browser. Upload a file instead.");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } });
    recChunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => e.data.size && recChunks.push(e.data);
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      recBlob = new Blob(recChunks, { type: recorder.mimeType || "audio/webm" });
      const a = $("#rec-audio"); a.src = URL.createObjectURL(recBlob); a.hidden = false;
      btn.textContent = "Record again"; btn.classList.remove("live");
      clearInterval(recTimer);
      attachMeter(stream, true);
    };
    recorder.start();
    attachMeter(stream);
    const t0 = Date.now();
    recTimer = setInterval(() => {
      const s = Math.floor((Date.now() - t0) / 1000);
      $("#rec-time").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    }, 250);
    btn.textContent = "Stop recording"; btn.classList.add("live");
  } catch (e) { toast("Microphone not available: " + e.message); }
}
function showAnalysis(v) {
  $("#analysis-card").hidden = false;
  const items = [
    ["Pitch (F0)", `${v.pitch.f0_median_hz} Hz`, v.pitch.register],
    ["Pitch range", `${v.pitch.range_semitones} st`, v.emotion.expressiveness],
    ["Vocal depth", `${v.depth.formant_scale_hz} Hz`, v.depth.label],
    ["Texture (HNR)", `${v.texture.hnr_db} dB`, `${v.texture.label} · jitter ${v.texture.jitter_percent}%`],
    ["Tone", `${v.tone.spectral_tilt_db} dB tilt`, v.tone.label],
    ["Speed", `${v.speed.estimated_wpm} wpm`, `${v.speed.syllables_per_s} syll/s · ${v.speed.label}`],
    ["Energy", `${v.energy.dynamic_range_db} dB range`, `variation ${v.energy.variation_db} dB`],
    ["Rhythm", `${v.rhythm.pauses_per_min}/min pauses`, `mean pause ${v.rhythm.mean_pause_s}s`],
    ["Breathing", `${v.rhythm.breath_count} breaths`, "detected in pauses"],
    ["Accent", v.accent.value, v.accent.source],
    ["Pronunciation", v.pronunciation.language, v.pronunciation.source],
  ];
  clear($("#analysis-out")).append(...items.map(([k, val, sub]) => h("div", {}, h("dt", {}, k), h("dd", {}, val, h("small", {}, sub)))));
}

// ---------- library ----------
function selectVoice(id) {
  state.activeVoice = id; store.set("voice", id);
  updateActiveVoice();
  if (!$('[data-view="library"]').hidden) renderLibrary();
}
async function renderLibrary() {
  const list = clear($("#library-list"));
  try { state.profiles = await api("/api/profiles"); } catch (e) { list.append(h("p", { class: "hint" }, e.message)); return; }
  updateActiveVoice();
  if (!state.profiles.length) {
    list.append(h("div", { class: "card" }, h("p", {}, "No voices yet."), h("a", { class: "btn primary", href: "#/clone" }, "Create a voice")));
    return;
  }
  for (const p of state.profiles) {
    const selected = p.id === state.activeVoice;
    list.append(h("article", { class: "card voice-card" + (selected ? " selected" : "") },
      h("p", { class: "eyebrow" }, p.kind === "designed" ? "Designed voice" : "Cloned voice"),
      h("h2", {}, p.name),
      h("p", { class: "hint" }, p.kind === "designed" ? (p.description || "Built from parameters") : `Speaker: ${p.speaker} · ${p.duration_s}s sample`),
      h("p", { class: "hint" }, `Language: ${p.language || "—"} · ${new Date(p.created_at).toLocaleDateString()}`),
      h("div", { class: "row" },
        h("button", { class: "btn " + (selected ? "" : "primary"), onclick: () => selectVoice(p.id) }, selected ? "Selected" : "Use this voice"),
        h("button", { class: "btn ghost", onclick: (e) => previewVoice(p.id, e.currentTarget) }, "Preview"),
        h("button", { class: "btn ghost danger", onclick: () => deleteVoice(p) }, "Delete"),
      )));
  }
}
async function previewVoice(id, btn) {
  const r = await busy(btn, () => api(`/api/profiles/${id}/preview`, { method: "POST", json: {} }));
  loadIntoPlayer(r.url + "?t=" + Date.now(), true);
}
async function deleteVoice(p) {
  if (!confirm(`Delete “${p.name}” and its encrypted recording? This cannot be undone.`)) return;
  try { await api(`/api/profiles/${p.id}`, { method: "DELETE" }); if (state.activeVoice === p.id) selectVoice(""); renderLibrary(); }
  catch (e) { toast(e.message); }
}

// ---------- intelligence ----------
function setupIntel() {
  scriptEl().value = store.get("script", "");
  scriptEl().addEventListener("input", () => store.set("script", scriptEl().value));
  $("#script-file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (f) setScript((await f.text()).slice(0, 50000));
  });
  $("#analyze-btn").addEventListener("click", async (e) => {
    if (!getScript()) return toast("Write or upload a script first.");
    const r = await busy(e.currentTarget, () => api("/api/script/analyze", { method: "POST", json: { text: getScript() } }));
    state.lastAnalysis = r;
    renderAnalysis(r);
  });
}
function bar(label, value, max = 100) {
  return h("div", { class: "bar-row" }, h("span", {}, label),
    h("div", { class: "bar" }, h("span", { style: `width:${Math.max(0, Math.min(100, value / max * 100))}%` })),
    h("span", { class: "mono" }, value));
}
function renderAnalysis(r) {
  $("#intel-out").hidden = false;
  $("#score-ring").style.setProperty("--v", r.score);
  $("#score-num").textContent = r.score;
  const L = r.language;
  $("#score-meta").textContent = `${r.stats.words} words · ${r.stats.sentences} sentences · ${L.is_mixed ? "mixed language" : (L.primary === "id" ? "Indonesian" : L.primary === "en" ? "English" : "unknown language")}`;
  const emo = Object.entries(r.emotion.scores).sort((a, b) => b[1] - a[1]).slice(0, 5);
  clear($("#emotion-bars")).append(
    h("p", {}, "Dominant: ", h("b", {}, cap(r.emotion.dominant)), ` · intensity ${r.emotion.intensity}/100`),
    ...emo.map(([k, v]) => bar(cap(k), v)));
  clear($("#param-cards")).append(...Object.entries(r.quality.parameters).map(([k, p]) => h("div", { class: "card param" },
    h("h3", {}, h("span", {}, k), h("span", { class: "mono" }, p.score)),
    h("div", { class: "bar" }, h("span", { style: `width:${p.score}%` })),
    p.issues.length ? h("ul", {}, ...p.issues.map((i) => h("li", {}, i))) : null,
    h("p", { class: "advice" }, p.advice))));
  const langBox = clear($("#lang-out"));
  langBox.append(h("div", { class: "tags" }, ...Object.entries(L.share).map(([k, v]) => h("span", { class: "pill" }, `${k} ${Math.round(v * 100)}%`))));
  if (L.unnatural_phrases.length) langBox.append(h("h3", {}, "Unnatural phrasing"), h("ul", { class: "changes" }, ...L.unnatural_phrases.map((u) => h("li", {}, `“${u.text}”: ${u.hint}`))));
  if (L.difficult_words.length) langBox.append(h("h3", {}, "Difficult words"), h("ul", { class: "changes" }, ...L.difficult_words.slice(0, 10).map((d) => h("li", {}, h("b", {}, d.word), ` — ${d.reasons.join(", ")}`))));
  if (!L.unnatural_phrases.length && !L.difficult_words.length) langBox.append(h("p", { class: "hint" }, "No unnatural phrasing or difficult words found."));
  const v = r.voiceover;
  const items = [["Speed", `${v.speaking_speed_wpm} wpm`], ["Duration", `${v.estimated_duration_s}s`], ["Pitch", v.pitch],
    ["Vocal intensity", v.vocal_intensity], ["Emotional intensity", `${v.emotional_intensity}/100`],
    ["Rhythm", `${v.sentence_rhythm.mean_words} words/sent`], ["Breathing points", v.breathing_points.length],
    ["Pronunciation difficulty", `${v.pronunciation_difficulty}/100`],
    ["Emphasis", v.emphasis.flatMap((e) => e.words).slice(0, 6).join(", ") || "—"]];
  clear($("#vo-out")).append(...items.map(([k, val]) => h("div", {}, h("dt", {}, k), h("dd", {}, String(val)))));
}

// ---------- enhancer ----------
const MODE_HINTS = { natural: "Human-like conversational delivery.", professional: "Studio-quality narration and commercial delivery.", expressive: "Emotionally engaging storytelling and narration." };
function setupEnhance() {
  const setMode = (m) => {
    state.mode = m; store.set("mode", m);
    $$("#mode-seg .seg-btn").forEach((b) => { b.classList.toggle("on", b.dataset.mode === m); b.setAttribute("aria-checked", b.dataset.mode === m); });
    $("#mode-hint").textContent = MODE_HINTS[m];
  };
  $$("#mode-seg .seg-btn").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  setMode(state.mode);
  $("#enhance-btn").addEventListener("click", async (e) => {
    if (!getScript()) return toast("Write a script in Script Intelligence first.");
    const r = await busy(e.currentTarget, () => api("/api/script/enhance", { method: "POST", json: { text: getScript(), mode: state.mode } }));
    renderEnhance(r);
  });
  $("#use-enhanced").addEventListener("click", () => { setScript($("#enh-text").textContent); toast("Enhanced script is now the working script."); });
  $("#keep-original").addEventListener("click", () => { $("#enhance-out").hidden = true; });
}
function renderEnhance(r) {
  $("#enhance-out").hidden = false;
  $("#orig-text").textContent = r.original;
  $("#enh-text").textContent = r.enhanced;
  $("#score-a").textContent = `score ${r.original_score}`;
  $("#score-b").textContent = `score ${r.enhanced_score}`;
  const pill = $("#meaning-pill");
  pill.textContent = r.meaning.preserved ? `Meaning kept · ${Math.round(r.meaning.content_words_kept * 100)}% content words` : "Check meaning";
  pill.className = "pill " + (r.meaning.preserved ? "ok" : "bad");
  clear($("#diff-out")).append(...r.diff.flatMap((d) => [d.op === "equal" ? d.text : h(d.op === "insert" ? "ins" : "del", {}, d.text), " "]));
  const ul = clear($("#changes-out"));
  if (!r.changes.length) ul.append(h("li", {}, "No changes needed."));
  for (const c of r.changes) ul.append(h("li", {}, h("b", {}, cap(c.rule)), c.before || c.after ? `: “${c.before}” → “${c.after}”` : ""));
}

// ---------- director ----------
function setupDirector() {
  $("#direct-btn").addEventListener("click", async (e) => {
    if (!getScript()) return toast("Write a script in Script Intelligence first.");
    const r = await busy(e.currentTarget, () => api("/api/script/direct", { method: "POST", json: { text: getScript(), mode: state.mode, emotion: $("#dir-emotion").value || null } }));
    $("#direct-out").hidden = false;
    clear($("#dir-cards")).append(...r.directions.map(dirCard));
    $("#dir-sheet").textContent = r.script;
  });
}
function dirCard(d) {
  const words = d.text.split(/\s+/);
  const said = h("p", { class: "said" });
  words.forEach((w, i) => {
    const bare = w.replace(/[^\p{L}\p{N}'-]/gu, "");
    said.append(d.prosody.emphasis.some((e) => e.toLowerCase() === bare.toLowerCase()) ? h("mark", {}, w) : w, " ");
    if (d.breath_after_word && i + 1 === d.breath_after_word) said.append(h("span", { class: "breath" }, "[breath]"), " ");
  });
  const p = d.prosody;
  const sign = (n) => (n > 0 ? "+" : "") + n;
  return h("article", { class: "card dir-card" },
    h("p", { class: "tone" }, d.tone), said,
    h("dl", { class: "metrics" },
      ...[["Rate", `${p.rate}×`], ["Pitch", `${sign(p.pitch_semitones)} st`], ["Range", `${p.pitch_range}×`], ["Volume", `${sign(p.volume_db)} dB`], ["Pause", `${d.pause_after_ms} ms`], ["Lang", d.language]]
        .map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v)))));
}

// ---------- studio ----------
function setupStudio() {
  const f = $("#studio-form");
  for (const r of $$("input[type=range]", f)) { r.addEventListener("input", () => syncOutput(r)); syncOutput(r); }
  $("#add-scene").addEventListener("click", () => { state.scenes.push({ label: `Scene ${state.scenes.length + 1}`, text: "", emotion: "" }); saveScenes(); renderScenes(); });
  f.addEventListener("submit", generate);
}
function renderStudio() {
  const vs = clear($("#studio-voice"));
  vs.append(h("option", { value: "" }, "Engine voice (no profile)"));
  for (const p of state.profiles) vs.append(h("option", { value: p.id, selected: p.id === state.activeVoice }, p.name));
  const es = clear($("#studio-engine"));
  es.append(h("option", { value: "" }, "Best available"));
  for (const e of (state.system ? state.system.engines : [])) es.append(h("option", { value: e.name, disabled: !e.available }, e.name + (e.available ? "" : " (not installed)")));
  $("#studio-form").mode.value = state.mode;
  renderScenes();
}
function saveScenes() { store.set("scenes", state.scenes); }
function renderScenes() {
  const ol = clear($("#scenes"));
  if (!state.scenes.length) {
    ol.append(h("li", { class: "scene" }, h("p", { class: "hint" }, getScript() ? `Working script: “${getScript().slice(0, 120)}${getScript().length > 120 ? "…" : ""}”` : "No script yet. Write one in Script Intelligence or add scenes.")));
    return;
  }
  state.scenes.forEach((s, i) => {
    const emo = h("select", { "aria-label": `Scene ${i + 1} emotion`, onchange: (e) => { s.emotion = e.target.value; saveScenes(); } },
      h("option", { value: "" }, "Automatic"), ...(state.system ? state.system.emotions : []).map((e) => h("option", { value: e, selected: e === s.emotion }, cap(e))));
    ol.append(h("li", { class: "scene" },
      h("div", { class: "row" },
        h("label", { class: "field" }, "Label", h("input", { value: s.label, oninput: (e) => { s.label = e.target.value; saveScenes(); } })),
        h("label", { class: "field" }, "Emotion", emo),
        h("button", { class: "btn ghost danger", type: "button", onclick: () => { state.scenes.splice(i, 1); saveScenes(); renderScenes(); } }, "Remove")),
      h("textarea", { rows: 3, "aria-label": `Scene ${i + 1} text`, placeholder: "What is said in this scene", oninput: (e) => { s.text = e.target.value; saveScenes(); } }, s.text)));
  });
}
function studioRequest() {
  const f = $("#studio-form");
  const pron = {};
  for (const line of f.pronunciation.value.split("\n")) {
    const [w, ...rest] = line.split("=");
    if (w && rest.length && w.trim() && rest.join("=").trim()) pron[w.trim()] = rest.join("=").trim();
  }
  const req = {
    profile_id: f.profile_id.value || null, engine: f.engine.value || null, mode: f.mode.value, emotion: f.emotion.value || null,
    speed: Number(f.speed.value), pitch: Number(f.pitch.value), volume_db: Number(f.volume_db.value), pause_scale: Number(f.pause_scale.value),
    pronunciation: pron, sample_rate: Number(f.sample_rate.value), target_lufs: Number(f.target_lufs.value),
    formats: $$("input[name=fmt]:checked", f).map((c) => c.value), enhance: f.enhance.checked,
  };
  const scenes = state.scenes.filter((s) => s.text.trim());
  if (scenes.length) req.segments = scenes.map((s) => ({ text: s.text, emotion: s.emotion || null, label: s.label }));
  else req.text = getScript();
  return req;
}
async function generate(ev) {
  ev.preventDefault();
  const req = studioRequest();
  if (!req.segments && !req.text) return toast("Add a script or scenes first.");
  if (!req.formats.length) return toast("Pick at least one format.");
  const btn = $("#gen-btn"), prog = $("#gen-progress");
  btn.disabled = true; prog.hidden = false; $("#result").hidden = true;
  try {
    const { job_id } = await api("/api/generate", { method: "POST", json: req });
    for (;;) {
      await new Promise((r) => setTimeout(r, 600));
      const job = await api(`/api/jobs/${job_id}`);
      $("#gen-bar").style.width = job.progress + "%";
      $("#gen-msg").textContent = cap(job.message);
      if (job.status === "failed") throw new Error(job.error);
      if (job.status === "done") { renderResult(job.result); break; }
    }
  } catch (e) { toast(e.message); $("#gen-msg").textContent = "Failed: " + e.message; } finally { btn.disabled = false; }
}
function renderResult(res) {
  $("#result").hidden = false;
  const dl = clear($("#downloads"));
  for (const [fmt, url] of Object.entries(res.urls)) dl.append(h("a", { class: "btn", href: withToken(url), download: "" }, `Download ${fmt.toUpperCase()}`));
  const m = res.mastering;
  const first = Object.values(res.files)[0];
  const items = [["Duration", `${m.duration_s}s`], ["Loudness", `${m.output_lufs} LUFS`], ["True peak", `${m.true_peak_dbtp} dBTP`],
    ["Sample rate", `${m.sample_rate} Hz`], ["Engine", res.engine], ["Voice", res.profile ? res.profile.name : "Engine voice"],
    ["Noise reduction", m.noise_reduction && m.noise_reduction.applied ? "Applied" : "Not needed"], ["Verified", `${first.probe.codec} · ${first.probe.channels} ch`],
    ["Render time", `${res.elapsed_s}s`]];
  clear($("#master-out")).append(...items.map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, String(v)))));
  const t = clear($("#sent-table"));
  t.append(h("thead", {}, h("tr", {}, ...["#", "Tone", "Rate", "Pitch", "Vol", "Emphasis", "Sentence"].map((x) => h("th", {}, x)))));
  t.append(h("tbody", {}, ...res.sentences.map((s) => h("tr", {},
    h("td", {}, s.sentence + 1), h("td", {}, s.tone), h("td", {}, s.prosody.rate), h("td", {}, s.prosody.pitch_semitones),
    h("td", {}, s.prosody.volume_db), h("td", {}, s.prosody.emphasis.join(", ")), h("td", {}, s.text)))));
  loadIntoPlayer(res.urls.wav || res.urls.mp3, false);
}

// ---------- projects ----------
function setupProjects() {
  $("#project-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const name = ev.target.name.value.trim();
    const data = { script: getScript(), scenes: state.scenes, mode: state.mode, voice: state.activeVoice };
    try { await api("/api/projects", { method: "POST", json: { name, data } }); ev.target.reset(); renderProjects(); toast("Project saved."); }
    catch (e) { toast(e.message); }
  });
}
async function renderProjects() {
  const list = clear($("#project-list"));
  let items = [];
  try { items = await api("/api/projects"); } catch (e) { list.append(h("p", { class: "hint" }, e.message)); return; }
  if (!items.length) { list.append(h("p", { class: "hint" }, "No saved projects yet.")); return; }
  for (const p of items) list.append(h("article", { class: "card" },
    h("h2", {}, p.name), h("p", { class: "hint" }, "Updated " + new Date(p.updated_at).toLocaleString()),
    h("div", { class: "row" },
      h("button", { class: "btn primary", onclick: () => openProject(p.id) }, "Open"),
      h("button", { class: "btn ghost danger", onclick: async () => { if (confirm(`Delete project “${p.name}”?`)) { await api(`/api/projects/${p.id}`, { method: "DELETE" }); renderProjects(); } } }, "Delete"))));
}
async function openProject(id) {
  const p = await api(`/api/projects/${id}`);
  setScript(p.data.script || "");
  state.scenes = p.data.scenes || []; saveScenes();
  if (p.data.mode) { state.mode = p.data.mode; store.set("mode", p.data.mode); }
  if (p.data.voice) selectVoice(p.data.voice);
  location.hash = "#/studio";
  toast(`Opened “${p.name}”.`);
}

// ---------- settings ----------
function setupSettings() {
  const f = $("#settings-form");
  f.key.value = store.get("key", "");
  f.addEventListener("submit", (ev) => { ev.preventDefault(); store.set("key", f.key.value.trim()); loadSystem().then(() => toast("Saved.")); });
}

// ---------- player, waveform, meter, 3D ----------
const player = $("#player");
let audioCtx = null, analyser = null, mediaSrc = null, peaks = null, liveStreamSrc = null;
function ensureCtx() {
  if (!audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    audioCtx = new Ctx();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.75;
  }
  return audioCtx;
}
function attachMeter(stream, detach = false) {
  if (!ensureCtx()) return;
  if (liveStreamSrc) { liveStreamSrc.disconnect(); liveStreamSrc = null; }
  if (!detach) { liveStreamSrc = audioCtx.createMediaStreamSource(stream); liveStreamSrc.connect(analyser); }
}
async function loadIntoPlayer(url, autoplay) {
  player.src = withToken(url);
  $("#play-btn").disabled = false;
  peaks = null;
  drawWave();
  try {
    const buf = await (await fetch(withToken(url))).arrayBuffer();
    const ctx = ensureCtx();
    if (ctx) {
      const audio = await ctx.decodeAudioData(buf);
      const ch = audio.getChannelData(0), n = 600, step = Math.floor(ch.length / n) || 1;
      peaks = new Float32Array(n);
      for (let i = 0; i < n; i++) { let m = 0; for (let j = i * step; j < (i + 1) * step && j < ch.length; j++) m = Math.max(m, Math.abs(ch[j])); peaks[i] = m; }
      drawWave();
    }
  } catch { /* waveform is optional; playback still works */ }
  if (autoplay) play();
}
function play() {
  const ctx = ensureCtx();
  if (ctx && !mediaSrc) { mediaSrc = ctx.createMediaElementSource(player); mediaSrc.connect(analyser); analyser.connect(ctx.destination); }
  if (ctx && ctx.state === "suspended") ctx.resume();
  player.play().catch((e) => toast("Playback failed: " + e.message));
}
$("#play-btn").addEventListener("click", () => (player.paused ? play() : player.pause()));
player.addEventListener("play", () => { $("#play-btn").classList.add("on"); $("#play-btn").setAttribute("aria-label", "Pause"); });
player.addEventListener("pause", () => { $("#play-btn").classList.remove("on"); $("#play-btn").setAttribute("aria-label", "Play"); });
player.addEventListener("timeupdate", () => {
  const t = player.currentTime;
  $("#t-cur").textContent = `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
  drawWave();
});
$("#wave").addEventListener("click", (e) => {
  if (!player.duration) return;
  const r = e.currentTarget.getBoundingClientRect();
  player.currentTime = ((e.clientX - r.left) / r.width) * player.duration;
});
function fitCanvas(c) {
  const dpr = window.devicePixelRatio || 1, w = c.clientWidth, hgt = c.clientHeight;
  if (c.width !== Math.round(w * dpr) || c.height !== Math.round(hgt * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(hgt * dpr); }
  const ctx = c.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return [ctx, w, hgt];
}
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function drawWave() {
  const [ctx, w, hgt] = fitCanvas($("#wave"));
  ctx.clearRect(0, 0, w, hgt);
  const mid = hgt / 2, progress = player.duration ? player.currentTime / player.duration : 0;
  const n = Math.max(40, Math.floor(w / 3));
  for (let i = 0; i < n; i++) {
    const v = peaks ? peaks[Math.floor(i / n * peaks.length)] : 0.04 + 0.03 * Math.sin(i * 0.4);
    const bh = Math.max(2, v * (hgt - 6));
    ctx.fillStyle = i / n < progress ? css("--accent") : css("--line");
    ctx.fillRect(i * 3, mid - bh / 2, 2, bh);
  }
}
const freq = new Uint8Array(256);
const history = [];
function frame(t) {
  const live = analyser && (!player.paused || liveStreamSrc);
  if (live) analyser.getByteFrequencyData(freq);
  // meter
  const m = $("#meter");
  if (m.offsetParent) {
    const [ctx, w, hgt] = fitCanvas(m);
    ctx.clearRect(0, 0, w, hgt);
    const bars = 16;
    for (let i = 0; i < bars; i++) {
      const v = live ? freq[Math.floor(i * 6 + 2)] / 255 : 0.06;
      ctx.fillStyle = v > 0.85 ? css("--rec") : css("--accent");
      ctx.globalAlpha = 0.35 + v * 0.65;
      const bh = Math.max(2, v * hgt);
      ctx.fillRect(i * (w / bars), hgt - bh, w / bars - 2, bh);
    }
    ctx.globalAlpha = 1;
  }
  // 3D spectrum terrain: each row is one moment, receding into the distance
  const c = $("#viz3d");
  if (c.offsetParent) {
    const row = new Float32Array(48);
    for (let i = 0; i < 48; i++) row[i] = live ? freq[Math.floor(i * 2.5 + 1)] / 255 : 0.12 + 0.1 * Math.sin(i * 0.35 + t / 700) * Math.cos(t / 1300 + i * 0.1);
    history.unshift(row); if (history.length > 34) history.pop();
    const [ctx, w, hgt] = fitCanvas(c);
    ctx.clearRect(0, 0, w, hgt);
    const horizon = hgt * 0.22, accent = css("--accent");
    for (let z = history.length - 1; z >= 0; z--) {
      const depth = z / 34, scale = 1 / (1 + depth * 3.2);
      const y0 = horizon + (hgt * 0.95 - horizon) * scale;
      ctx.beginPath();
      history[z].forEach((v, i) => {
        const x = w / 2 + (i / 47 - 0.5) * w * 1.25 * scale;
        const y = y0 - v * hgt * 0.55 * scale;
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.strokeStyle = accent;
      ctx.globalAlpha = 0.08 + 0.85 * (1 - depth);
      ctx.lineWidth = 1.6 * scale + 0.3;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
  requestAnimationFrame(frame);
}

// ---------- boot ----------
setupClone(); setupIntel(); setupEnhance(); setupDirector(); setupStudio(); setupProjects(); setupSettings();
window.addEventListener("hashchange", route);
window.addEventListener("resize", drawWave);
loadSystem().then(route);
requestAnimationFrame(frame);
