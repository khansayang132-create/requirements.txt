/* NOVA Studio screens: idea to production, emotion director, queue & history, schedule, insights.
   Uses app.js helpers (h, api, busy, toast, loadIntoPlayer). All text from the server is inserted
   as text nodes, never as HTML. */
(() => {
  const STAGE_NAMES = { intent: "Understand", concepts: "Concepts", script: "Script", analysis: "Analysis",
    enhancement: "Enhance", emotion: "Emotion", voice: "Voice", audio: "Narration", subtitles: "Subtitles",
    qa: "Quality check", deliver: "Deliver" };
  const fileUrl = (pid, name) => `/api/v100/productions/${pid}/files/${name}`;
  const fmtTime = (iso) => iso ? new Date(iso).toLocaleString() : "—";
  const statusPill = (s) => h("span", { class: "pill " + ({ completed: "ok", failed: "bad", failed_qa: "bad",
    succeeded: "ok" }[s] || "") }, s.replace("_", " "));
  const short = (t, n = 70) => !t || t.length <= n ? (t || "") : t.slice(0, t.lastIndexOf(" ", n) > 20 ? t.lastIndexOf(" ", n) : n) + "…";
  let watching = null;
  let loaded = { produce: false, schedule: false };

  // ---------- idea to production ----------
  async function setupProduce() {
    if (loaded.produce) return;
    loaded.produce = true;
    const [catalog, status] = await Promise.all([api("/api/v100/voice/catalog"), api("/api/v100/status")]);
    const vs = $("#prod-voice");
    clear(vs).append(h("option", { value: "" }, "Default voice for the language"));
    for (const v of catalog) vs.append(h("option", { value: v.id }, `${v.name} · ${v.kind}`));
    const preset = catalog.find((v) => v.id === "preset:soft-young-indonesian-woman");
    if (preset) vs.value = preset.id;
    const en = $("#prod-enhance");
    for (const [k, label] of [["natural", "Natural conversation"], ["cinematic", "Cinematic"], ["deep_emotional", "Deep emotional"],
      ["professional", "Professional narration"], ["motivational", "Motivational"], ["documentary", "Documentary"],
      ["social", "Social media"], ["persuasive", "Persuasive business"]]) en.append(h("option", { value: k }, label));
    $("#prod-llm-hint").textContent = status.llm
      ? "Local AI connected: concepts, scripts and enhancement are written by your own model."
      : "No AI model connected: paste your own script, or connect a local model in Settings.";
    $("#prod-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const body = { language: f.get("language"), duration_s: Number(f.get("duration_s")), mode: f.get("mode") };
      const idea = f.get("idea").trim(), script = f.get("script").trim();
      if (script) body.script = script; else if (idea) body.idea = idea;
      else { toast("Write an idea or paste a script."); return; }
      if (f.get("voice")) body.voice = f.get("voice");
      if (f.get("enhance_mode")) body.enhance_mode = f.get("enhance_mode");
      await busy(e.submitter, async () => {
        const p = await api("/api/v100/productions", { method: "POST", json: body });
        toast("Production started.");
        watch(p.id, $("#prod-live"));
      });
    });
  }

  function stageRail(p) {
    return h("ol", { class: "stages", "aria-label": "Production stages" }, p.stages.map((s) =>
      h("li", { class: "stage " + s.status, title: s.error || "" }, h("span", { class: "dot", "aria-hidden": "true" }),
        h("span", {}, STAGE_NAMES[s.stage] || s.stage), h("span", { class: "sr-only" }, ` ${s.status}`))));
  }

  function renderProduction(p, box) {
    clear(box);
    const head = h("div", { class: "row spread" }, h("h2", {}, (p.stages.find((s) => s.stage === "script")?.output?.title) || p.idea || "Production"),
      statusPill(p.status));
    const card = h("div", { class: "card" }, head, stageRail(p));
    if (p.error) card.append(h("p", { class: "hint bad-text" }, p.error));
    if (["failed", "interrupted", "failed_qa"].includes(p.status)) {
      card.append(h("button", { class: "btn", type: "button", onclick: async (e) => busy(e.target, async () => {
        await api(`/api/v100/productions/${p.id}/resume`, { method: "POST" }); watch(p.id, box);
      }) }, "Resume from last finished stage"));
    }
    box.append(card);
    const out = Object.fromEntries(p.stages.filter((s) => s.output).map((s) => [s.stage, s.output]));
    if (out.concepts && out.concepts.concepts?.length) {
      box.append(h("div", { class: "card" }, h("h2", {}, "Concepts"), h("div", { class: "grid" }, out.concepts.concepts.map((c, i) =>
        h("div", { class: "concept" + (i === out.concepts.chosen ? " chosen" : "") }, h("h3", {}, c.title), h("p", {}, `“${c.hook}”`),
          h("p", { class: "hint" }, `${c.emotional_direction} · ${c.duration_s}s · ${c.platform}`))))));
    }
    if (out.script) {
      const final = out.enhancement && !out.enhancement.skipped && out.enhancement.accepted ? out.enhancement.text : out.script.text;
      box.append(h("div", { class: "card" }, h("h2", {}, "Script"),
        h("p", { class: "hint" }, `${out.script.words || ""} words · estimated ${out.script.estimated_s ?? "?"}s for ${out.script.target_s ?? "?"}s`
          + (out.enhancement && !out.enhancement.skipped ? (out.enhancement.accepted ? " · enhanced" : " · enhancement rejected: " + out.enhancement.note) : "")),
        h("pre", { class: "sheet" }, final)));
    }
    if (out.emotion) {
      box.append(h("div", { class: "card" }, h("h2", {}, "Emotion timeline"),
        h("p", { class: "hint" }, `Arc: ${out.emotion.arc.opening} → ${out.emotion.arc.middle} → ${out.emotion.arc.ending} (${out.emotion.arc.shape})`),
        h("div", { class: "timeline" }, out.emotion.sentences.map((d) => h("div", { class: "beat", style: `--i:${d.intensity}` },
          h("b", {}, d.emotion), h("span", { class: "mono" }, `${d.intensity}`), h("p", {}, d.text))))));
    }
    if (p.status === "completed" || p.assets?.length) {
      const qa = p.qa?.report;
      box.append(h("div", { class: "card" }, h("h2", {}, "Result"),
        h("div", { class: "row" },
          h("button", { class: "btn primary", type: "button", onclick: () => loadIntoPlayer(fileUrl(p.id, "production.wav"), true) }, "Play"),
          ["production.wav", "production.mp3", "subtitles.srt", "subtitles.vtt", "subtitles.json", "subtitles.txt"].map((n) =>
            h("a", { class: "btn ghost", href: withToken(fileUrl(p.id, n)), download: "" }, n.split(".").pop().toUpperCase()))),
        out.audio ? h("p", { class: "hint" }, `${out.audio.duration_s}s · ${out.audio.engine} · ${out.audio.mastering.output_lufs} LUFS · peak ${out.audio.mastering.true_peak_dbtp} dBTP`) : null,
        qa ? h("table", { class: "tbl" }, h("caption", {}, qa.passed ? "Quality check passed" : "Quality check failed"),
          qa.checks.map((c) => h("tr", {}, h("td", { class: c.ok === true ? "ok" : c.ok === false ? "over" : "" },
            c.ok === true ? "pass" : c.ok === false ? "fail" : "skipped"), h("td", {}, c.check), h("td", {}, typeof c.detail === "string" ? c.detail : JSON.stringify(c.detail))))) : null,
        h("div", { class: "row" }, h("span", { class: "hint" }, "Rate this production:"), [1, 2, 3, 4, 5].map((n) =>
          h("button", { class: "btn ghost", type: "button", "aria-label": `${n} of 5`, onclick: async (e) => busy(e.target, async () => {
            await api(`/api/v100/productions/${p.id}/feedback`, { method: "POST", json: { rating: n } }); toast("Thanks: saved for Insights.");
          }) }, "★".repeat(n))))));
    }
  }

  async function watch(pid, box) {
    watching = pid;
    for (;;) {
      if (watching !== pid) return;
      let p;
      try { p = await api(`/api/v100/productions/${pid}`); } catch (e) { toast(e.message); return; }
      renderProduction(p, box);
      if (!["queued", "running"].includes(p.status)) return;
      await new Promise((r) => setTimeout(r, 2500));
    }
  }

  // ---------- emotion director ----------
  let emoState = null;
  async function setupEmotion() {
    const list = (await api("/api/v100/productions?limit=50")).filter((p) => p.status !== "queued");
    const sel = clear($("#emo-prod"));
    sel.append(h("option", { value: "" }, list.length ? "Choose a production" : "No productions yet"));
    for (const p of list) sel.append(h("option", { value: p.id }, `${short(p.idea || "script", 60)} · ${p.status}`));
    sel.onchange = () => loadTimeline(sel.value);
    $("#emo-redo").onclick = async (e) => busy(e.target, async () => {
      await api(`/api/v100/productions/${emoState.pid}/redo/audio`, { method: "POST" });
      toast("Re-rendering the audio with your emotions.");
      location.hash = "#/queue";
    });
  }

  async function loadTimeline(pid) {
    const box = clear($("#emo-timeline"));
    $("#emo-redo").disabled = true;
    if (!pid) return;
    const p = await api(`/api/v100/productions/${pid}`);
    if (!p.script_version_id) { box.append(h("p", { class: "hint" }, "This production has no emotion timeline yet.")); return; }
    const [tl, lib] = await Promise.all([api(`/api/v100/emotion/${p.script_version_id}`), api("/api/v100/emotion/library")]);
    emoState = { pid, vid: p.script_version_id };
    $("#emo-redo").disabled = false;
    tl.forEach((d) => box.append(beatEditor(d, lib)));
  }

  function beatEditor(d, lib) {
    const emo = h("select", { "aria-label": `Emotion for sentence ${d.index + 1}` }, lib.map((l) => h("option", { value: l.emotion }, l.emotion)));
    emo.value = d.emotion;
    const inten = h("input", { type: "range", min: 10, max: 100, value: d.intensity, "aria-label": `Intensity for sentence ${d.index + 1}` });
    const val = h("output", { class: "mono" }, d.intensity);
    const after = h("input", { type: "number", min: 0, max: 5000, step: 50, value: d.pause_after_ms, "aria-label": "Pause after (ms)" });
    inten.oninput = () => { val.textContent = inten.value; };
    const save = async () => {
      try {
        await api(`/api/v100/emotion/${emoState.vid}/${d.index}`, { method: "PUT",
          json: { emotion: emo.value, intensity: Number(inten.value), pause_after_ms: Number(after.value) } });
        toast(`Sentence ${d.index + 1}: ${emo.value} ${inten.value}`);
      } catch (e) { toast(e.message); }
    };
    emo.onchange = save; inten.onchange = save; after.onchange = save;
    return h("div", { class: "beat-edit" + (d.edited ? " edited" : "") },
      h("p", {}, h("span", { class: "mono" }, `${d.index + 1}. `), d.text),
      h("p", { class: "hint" }, `${d.delivery} · ${d.speed} · pitch ${d.pitch_direction} · ${d.transition_from_previous}`),
      h("div", { class: "row" }, h("label", { class: "field" }, "Emotion", emo),
        h("label", { class: "field grow" }, "Intensity ", val, inten),
        h("label", { class: "field" }, "Pause after (ms)", after)));
  }

  // ---------- queue & history ----------
  async function renderQueue() {
    const rows = await api("/api/v100/productions?limit=100");
    const t = clear($("#queue-table"));
    t.append(h("tr", {}, ["Idea", "Status", "Stage", "Started", ""].map((x) => h("th", {}, x))));
    for (const p of rows) t.append(h("tr", {}, h("td", {}, short(p.idea || "own script")), h("td", {}, statusPill(p.status)),
      h("td", {}, p.current_stage || "—"), h("td", {}, fmtTime(p.created_at)),
      h("td", {}, h("button", { class: "btn ghost", type: "button", onclick: () => watch(p.id, $("#queue-detail")) }, "Open"))));
    if (!rows.length) t.append(h("tr", {}, h("td", { colspan: 5 }, "No productions yet: start one in Idea to Production.")));
  }

  // ---------- schedule ----------
  async function setupSchedule() {
    if (!loaded.schedule) {
      loaded.schedule = true;
      $("#job-tz").value = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      const days = $("#job-days");
      ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach((d, i) => days.append(h("label", { class: "check" },
        h("input", { type: "checkbox", name: "day", value: i, checked: i < 5 }), d)));
      $("#job-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = new FormData(e.target), type = f.get("type");
        const schedule = { type };
        if (type === "daily" || type === "weekly") schedule.time = f.get("time");
        if (type === "weekly") schedule.days = f.getAll("day").map(Number);
        if (type === "once") { if (!f.get("date")) { toast("Choose a date."); return; } schedule.at = `${f.get("date")}T${f.get("time")}`; }
        if (type === "interval") schedule.minutes = Number(f.get("minutes"));
        await busy(e.submitter, async () => {
          await api("/api/v100/schedule/jobs", { method: "POST", json: { name: f.get("name"), timezone: f.get("timezone"),
            schedule, production: { idea: f.get("idea"), voice: "preset:soft-young-indonesian-woman" } } });
          toast("Scheduled."); e.target.reset(); $("#job-tz").value = f.get("timezone"); renderSchedule();
        });
      });
      const plat = $("#cal-form [name=platform]");
      const showTimes = async () => { const r = await api(`/api/v100/calendar/times/${plat.value}`); $("#cal-times").textContent = `Suggested times: ${r.times_local.join(", ")} (${r.basis})`; };
      plat.onchange = showTimes; showTimes();
      $("#cal-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = new FormData(e.target);
        await busy(e.submitter, async () => {
          await api("/api/v100/calendar", { method: "POST", json: { date: f.get("date"), time: f.get("time") || null, title: f.get("title"),
            platform: f.get("platform"), category: f.get("category") || null, timezone: $("#job-tz").value } });
          toast("Added to the calendar."); e.target.reset(); renderSchedule();
        });
      });
    }
    renderSchedule();
  }

  async function renderSchedule() {
    const [jobs, runs, cal] = await Promise.all([api("/api/v100/schedule/jobs"), api("/api/v100/schedule/runs"), api("/api/v100/calendar")]);
    const jt = clear($("#job-table"));
    jt.append(h("tr", {}, ["Job", "Schedule", "Next run", "Time zone", "Last", ""].map((x) => h("th", {}, x))));
    for (const j of jobs.filter((j) => j.last_status !== "deleted")) {
      const s = j.schedule;
      const desc = s.type === "daily" ? `daily ${s.time}` : s.type === "weekly" ? `weekly ${s.time} (${s.days.join(",")})`
        : s.type === "interval" ? `every ${s.minutes} min` : `once ${s.at}`;
      jt.append(h("tr", {}, h("td", {}, j.name), h("td", {}, desc), h("td", { class: "mono" }, j.next_run_local ? j.next_run_local.replace("T", " ").slice(0, 16) : "—"),
        h("td", {}, j.timezone), h("td", {}, statusPill(j.last_status || "scheduled")),
        h("td", {}, h("button", { class: "btn ghost", type: "button", onclick: async (e) => busy(e.target, async () => {
          await api(`/api/v100/schedule/jobs/${j.id}/enable?enabled=${!j.enabled}`, { method: "POST" }); renderSchedule();
        }) }, j.enabled ? "Pause" : "Resume"))));
    }
    if (!jobs.some((j) => j.last_status !== "deleted")) jt.append(h("tr", {}, h("td", { colspan: 6 }, "No jobs yet: schedule one above.")));
    const rt = clear($("#run-table"));
    rt.append(h("tr", {}, ["Scheduled for", "Attempt", "Status", "Production", "Error"].map((x) => h("th", {}, x))));
    for (const r of runs) rt.append(h("tr", {}, h("td", { class: "mono" }, r.scheduled_for.slice(0, 16)), h("td", {}, r.attempt),
      h("td", {}, statusPill(r.status)), h("td", { class: "mono" }, r.production_id ? r.production_id.slice(0, 8) : "—"), h("td", {}, r.error || "")));
    if (!runs.length) rt.append(h("tr", {}, h("td", { colspan: 5 }, "No runs yet.")));
    const ct = clear($("#cal-table"));
    ct.append(h("tr", {}, ["Date", "Time", "Title", "Platform", "Status"].map((x) => h("th", {}, x))));
    for (const c of cal) {
      const st = h("select", { "aria-label": `Status of ${c.title}` }, ["idea", "scripted", "scheduled", "produced", "published", "skipped"].map((s) => h("option", { value: s }, s)));
      st.value = c.status;
      st.onchange = async () => { try { await api(`/api/v100/calendar/${c.id}`, { method: "PATCH", json: { status: st.value } }); toast("Status saved."); } catch (e) { toast(e.message); } };
      ct.append(h("tr", {}, h("td", { class: "mono" }, c.date), h("td", { class: "mono" }, c.time || "—"), h("td", {}, c.title),
        h("td", {}, c.platform || "—"), h("td", {}, st)));
    }
    if (!cal.length) ct.append(h("tr", {}, h("td", { colspan: 5 }, "Nothing planned yet.")));
  }

  // ---------- insights ----------
  async function renderInsights() {
    const [rep, notes] = await Promise.all([api("/api/v100/learning"), api("/api/v100/notifications")]);
    clear($("#ins-sugg")).append(...rep.suggestions.map((s) => h("li", {}, s)));
    $("#ins-obs").textContent = JSON.stringify({ samples: rep.samples, ...rep.observed }, null, 2);
    const ul = clear($("#ins-notes"));
    ul.append(...notes.slice(0, 20).map((n) => h("li", {}, h("span", { class: "pill " + (n.level === "error" ? "bad" : "") }, n.level), " ",
      h("span", { class: "mono" }, fmtTime(n.ts)), " ", n.message)));
    if (!notes.length) ul.append(h("li", { class: "hint" }, "No notifications."));
    $("#ins-reset").onclick = async (e) => busy(e.target, async () => {
      if (!confirm("Reset learned preferences? Ratings and history are kept.")) return;
      const r = await api("/api/v100/learning/reset", { method: "POST" }); toast(`Removed ${r.preferences_removed} preferences.`); renderInsights();
    });
  }

  window.studioRoute = (view) => {
    const run = { produce: setupProduce, emotion: setupEmotion, queue: renderQueue, schedule: setupSchedule, insights: renderInsights }[view];
    if (run) run().catch((e) => toast(e.message));
  };
  $("#queue-refresh").addEventListener("click", () => renderQueue().catch((e) => toast(e.message)));
  if (window.studioRoute && location.hash.match(/^#\/(produce|emotion|queue|schedule|insights)/)) window.studioRoute(location.hash.slice(2));
})();
