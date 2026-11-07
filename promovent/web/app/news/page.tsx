"use client";
import { useApi } from "@/lib/api";
import { utc } from "@/lib/format";
import { DataBadge, Panel, StateView, Table } from "@/components/ui";

type Item = { source: string; title: string; url: string; published: string; provider: string; sentiment: { label: string; categories: string[]; assets: string[] } };
type N = { items: Item[]; errors: Record<string, string>; fear_greed: { value: number; classification: string; timestamp: number } | null;
  sentiment: Record<string, { bullish: number; bearish: number; neutral: number; n: number; net: number }>; breaking: Item[]; fetched_at: string };

const tone = (l: string) => (l === "bullish" ? "text-up" : l === "bearish" ? "text-down" : "text-muted");

export default function News() {
  const n = useApi<N>("/api/news", 120000);
  return (
    <>
      <h1 className="text-lg font-semibold">News and sentiment</h1>
      <StateView load={n}>{(d) => <>
        {Object.keys(d.errors).length ? <Panel title="Sources unavailable" badge={<DataBadge kind={d.items.length ? "live" : "unavailable"} note="see errors" />}>
          <ul className="grid gap-1 text-sm">{Object.entries(d.errors).map(([k, v]) => <li key={k}><b>{k}</b>: <span className="text-down">{v}</span></li>)}</ul>
        </Panel> : null}
        <div className="grid-cards">
          <Panel title="Fear & Greed (alternative.me)" className="lg:col-span-4">
            {d.fear_greed ? <p><b className="font-mono text-2xl">{d.fear_greed.value}</b> <span className="text-muted">{d.fear_greed.classification} · {utc(d.fear_greed.timestamp * 1000)}</span></p>
              : <p className="text-sm italic text-muted">Unavailable.</p>}
          </Panel>
          <Panel title="Headline sentiment by asset" className="lg:col-span-8">
            <Table head={["Asset", "Bullish", "Bearish", "Neutral", "Net"]} empty="No headlines to score."
              rows={Object.entries(d.sentiment).map(([a, s]) => [a, s.bullish, s.bearish, s.neutral, <span key="n" className={s.net > 0 ? "text-up" : s.net < 0 ? "text-down" : ""}>{s.net}</span>])} />
            <p className="mt-2 text-xs text-muted">Lexicon tags on headlines (CryptoPanic votes override when there are 5+). Rough sentiment, not a forecast.</p>
          </Panel>
        </div>
        {d.breaking.length ? <Panel title="Regulatory and exchange incidents">
          <ul className="grid gap-2 text-sm">{d.breaking.map((i) => <li key={i.url}><a href={i.url} target="_blank" rel="noopener noreferrer">{i.title}</a> <span className="text-muted">· {i.source} · {utc(i.published)}</span></li>)}</ul>
        </Panel> : null}
        <Panel title="Latest" badge={<DataBadge kind={d.items.length ? "live" : "unavailable"} meta={{ exchange: "news sources", timestamp_ms: Date.parse(d.fetched_at) }} note="no source returned items" />}>
          <Table head={["Published", "Source", "Headline", "Sentiment", "Tags"]} empty="No headlines returned by any source."
            rows={d.items.slice(0, 60).map((i) => [utc(i.published), i.source, <a key="t" href={i.url} target="_blank" rel="noopener noreferrer" className="whitespace-normal">{i.title}</a>,
              <span key="s" className={tone(i.sentiment.label)}>{i.sentiment.label}</span>, [...i.sentiment.assets, ...i.sentiment.categories].join(", ") || "–"])} />
        </Panel>
      </>}</StateView>
    </>
  );
}
