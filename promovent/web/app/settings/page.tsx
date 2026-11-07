"use client";
import { useEffect, useState } from "react";
import { ApiError, getKey, post, setKey, useApi } from "@/lib/api";
import { label } from "@/lib/format";
import { ErrorBox, Field, Panel, StateView, Table } from "@/components/ui";

type Prefs = { telegram_chat_id: string | null; email: string | null; alert_prefs: Record<string, string[]>; events: string[]; channels: Record<string, string> };
type Note = { id: number; ts: string; channel: string; event: string; subject: string; status: string; error: string | null; attempts: number };

export default function Settings() {
  const [key, setK] = useState("");
  const [saved, setSaved] = useState("");
  useEffect(() => setK(getKey()), []);
  const prefs = useApi<Prefs>("/api/settings/alerts");
  const notes = useApi<Note[]>("/api/notifications", 30000);
  const [form, setForm] = useState<Prefs | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { if (prefs.data) setForm(prefs.data); }, [prefs.data]);
  const toggle = (ev: string, ch: string) => form && setForm({ ...form, alert_prefs: { ...form.alert_prefs,
    [ev]: (form.alert_prefs[ev] || []).includes(ch) ? form.alert_prefs[ev].filter((c) => c !== ch) : [...(form.alert_prefs[ev] || []), ch] } });
  const save = async () => { if (!form) return; setErr(null); setMsg("");
    try { await post("/api/settings/alerts", { telegram_chat_id: form.telegram_chat_id || null, email: form.email || null, alert_prefs: form.alert_prefs }, "PUT"); setMsg("Saved."); }
    catch (e) { setErr(e as ApiError); } };
  const test = async () => { setErr(null); try { const r = await post<{ channel: string; status: string; error: string | null }[]>("/api/settings/alerts/test", {});
    setMsg(r.map((x) => `${x.channel}: ${x.status}${x.error ? ` (${x.error})` : ""}`).join("; ") || "No channels selected."); notes.reload(); } catch (e) { setErr(e as ApiError); } };
  return (
    <>
      <h1 className="text-lg font-semibold">Settings</h1>
      <Panel title="API key">
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); setKey(key.trim()); setSaved("Stored for this browser tab. Reloading data…"); setTimeout(() => location.reload(), 400); }}>
          <div className="min-w-[240px] flex-1"><Field label="X-API-Key (kept in this tab's session storage only)"><input className="input font-mono" type="password" autoComplete="off" value={key} onChange={(e) => setK(e.target.value)} /></Field></div>
          <button className="btn-primary" type="submit">Save key</button>
          <button className="btn" type="button" onClick={() => { setKey(""); setK(""); setSaved("Cleared."); }}>Clear</button>
        </form>
        {saved ? <p className="mt-2 text-sm text-muted" role="status">{saved}</p> : null}
      </Panel>
      <Panel title="Alert delivery">
        <StateView load={prefs}>{() => form ? <>
          <p className="mb-3 text-sm text-muted">Server channels: Telegram {form.channels.telegram}; email {form.channels.email}.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Telegram chat id (numbers only; message your bot, then use getUpdates)"><input className="input" inputMode="numeric" value={form.telegram_chat_id || ""} onChange={(e) => setForm({ ...form, telegram_chat_id: e.target.value })} /></Field>
            <Field label="Email"><input className="input" type="email" value={form.email || ""} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          </div>
          <div className="mt-4"><Table head={["Event", "Telegram", "Email"]} rows={form.events.map((ev) => [label(ev), ...["telegram", "email"].map((ch) => (
            <label key={ch} className="inline-flex min-h-[44px] min-w-[44px] items-center gap-2"><input type="checkbox" className="h-6 w-6 accent-[#e8b04b]" checked={(form.alert_prefs[ev] || []).includes(ch)} onChange={() => toggle(ev, ch)} aria-label={`${ev} by ${ch}`} /></label>))])} /></div>
          <div className="mt-3 flex flex-wrap gap-2"><button className="btn-primary" type="button" onClick={save}>Save preferences</button><button className="btn" type="button" onClick={test}>Send test</button></div>
          {msg ? <p className="mt-2 text-sm" role="status">{msg}</p> : null}
          {err ? <div className="mt-2"><ErrorBox error={err} /></div> : null}
        </> : null}</StateView>
      </Panel>
      <Panel title="Delivery log">
        <StateView load={notes} isEmpty={(n) => n.length === 0} empty="No notifications attempted yet.">
          {(n) => <Table head={["Time", "Channel", "Event", "Subject", "Status", "Attempts", "Error"]} rows={n.map((x) => [x.ts.slice(0, 19).replace("T", " "), x.channel, label(x.event), x.subject,
            <span key="s" className={x.status === "sent" ? "text-up" : x.status === "failed" ? "text-down" : "text-muted"}>{x.status}</span>, x.attempts, x.error || "–"])} />}
        </StateView>
      </Panel>
    </>
  );
}
