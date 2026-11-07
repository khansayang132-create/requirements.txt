import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ApiError, type Load } from "@/lib/api";
import { DataBadge, StateView, Table, kindOf } from "@/components/ui";

it("labels live, simulated and unavailable data distinctly", () => {
  expect(kindOf({ source: "live" })).toBe("live");
  expect(kindOf({ source: "synthetic" })).toBe("simulated");
  expect(kindOf(undefined, new ApiError(503, "x", "unavailable"))).toBe("unavailable");
  render(<><DataBadge kind="live" meta={{ exchange: "binance", timestamp_ms: Date.now() }} /><DataBadge kind="simulated" /><DataBadge kind="unavailable" note="binance: 403" /></>);
  expect(screen.getAllByTestId("data-badge").map((b) => b.textContent)).toEqual(["LIVE", "SIMULATED", "UNAVAILABLE"]);
  expect(screen.getByText("binance: 403")).toBeInTheDocument();
});

const L = <T,>(x: Partial<Load<T>>): Load<T> => ({ loading: false, reload: () => {}, ...x });

it("StateView shows loading, error, offline, empty and stale states", () => {
  const { rerender } = render(<StateView load={L<number[]>({ loading: true })}>{() => <p>data</p>}</StateView>);
  expect(screen.getByRole("status")).toHaveTextContent("Loading");
  rerender(<StateView load={L<number[]>({ error: new ApiError(0, "Backend unreachable.", "offline") })}>{() => <p>data</p>}</StateView>);
  expect(screen.getByRole("alert")).toHaveTextContent("Offline");
  rerender(<StateView load={L<number[]>({ data: [] })} isEmpty={(d) => d.length === 0} empty="Nothing here">{() => <p>data</p>}</StateView>);
  expect(screen.getByText("Nothing here")).toBeInTheDocument();
  rerender(<StateView load={L<number[]>({ data: [1], error: new ApiError(503, "down", "unavailable") })}>{() => <p>data</p>}</StateView>);
  expect(screen.getByRole("alert")).toHaveTextContent("showing last good data");
  expect(screen.getByText("data")).toBeInTheDocument();
});

it("Table renders an empty row message", () => {
  render(<Table head={["A"]} rows={[]} empty="No rows yet" />);
  expect(screen.getByText("No rows yet")).toBeInTheDocument();
});
