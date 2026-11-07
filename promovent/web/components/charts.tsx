"use client";
import { useEffect, useRef } from "react";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";

const C = { up: "#2fbf9f", down: "#ef7a6e", line: "#262e38", text: "#9aa4b2", accent: "#e8b04b" };
export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
export type Marker = { time: number; kind: string };

function base(el: HTMLElement) {
  // Imported lazily: lightweight-charts touches `window`.
  return import("lightweight-charts").then(({ createChart }) =>
    createChart(el, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: C.text, fontFamily: "ui-monospace, Menlo, monospace", attributionLogo: false },
      grid: { vertLines: { color: C.line }, horzLines: { color: C.line } },
      timeScale: { timeVisible: true, borderColor: C.line }, rightPriceScale: { borderColor: C.line },
    }));
}

export function CandleChart({ candles, markers = [], levels = [], label }: { candles: Candle[]; markers?: Marker[]; levels?: { price: number; title: string; up: boolean }[]; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<{ c: ISeriesApi<"Candlestick">; v: ISeriesApi<"Histogram"> } | null>(null);
  useEffect(() => {
    let dead = false;
    base(ref.current!).then((ch) => {
      if (dead) return ch.remove();
      chart.current = ch;
      const c = ch.addCandlestickSeries({ upColor: C.up, downColor: C.down, borderVisible: false, wickUpColor: C.up, wickDownColor: C.down });
      const v = ch.addHistogramSeries({ priceScaleId: "", priceFormat: { type: "volume" } });
      v.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      series.current = { c, v };
    });
    return () => { dead = true; chart.current?.remove(); chart.current = null; series.current = null; };
  }, []);
  useEffect(() => {
    const draw = () => {
      const s = series.current;
      if (!s) return void setTimeout(draw, 50);
      s.c.setData(candles.map((k) => ({ ...k, time: k.time as UTCTimestamp })));
      s.v.setData(candles.map((k) => ({ time: k.time as UTCTimestamp, value: k.volume, color: k.close >= k.open ? "rgba(47,191,159,.35)" : "rgba(239,122,110,.35)" })));
      s.c.setMarkers(markers.slice(-8).map((m) => ({ time: m.time as UTCTimestamp, position: m.kind.endsWith("UP") ? "belowBar" : "aboveBar",
        color: m.kind.endsWith("UP") ? C.up : C.down, shape: m.kind.endsWith("UP") ? "arrowUp" : "arrowDown", text: m.kind.replace("_", " ") })));
      levels.forEach((l) => s.c.createPriceLine({ price: l.price, color: l.up ? C.up : C.down, lineStyle: 2, title: l.title }));
      chart.current?.timeScale().fitContent();
    };
    draw();
  }, [candles, markers, levels]);
  return <div ref={ref} className="h-[280px] w-full sm:h-[380px]" role="img" aria-label={label} />;
}

export function LineChart({ points, label }: { points: { time: number; value: number }[]; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const line = useRef<ISeriesApi<"Line"> | null>(null);
  const chart = useRef<IChartApi | null>(null);
  useEffect(() => {
    let dead = false;
    base(ref.current!).then((ch) => {
      if (dead) return ch.remove();
      chart.current = ch;
      line.current = ch.addLineSeries({ color: C.accent, lineWidth: 2 });
    });
    return () => { dead = true; chart.current?.remove(); };
  }, []);
  useEffect(() => {
    const draw = () => {
      if (!line.current) return void setTimeout(draw, 50);
      line.current.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      chart.current?.timeScale().fitContent();
    };
    draw();
  }, [points]);
  return <div ref={ref} className="h-[220px] w-full" role="img" aria-label={label} />;
}
