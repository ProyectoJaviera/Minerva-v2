import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IndicatorsTab } from "./IndicatorsTab";
import { mockFetch, withQueryClient } from "./testUtils";

const NOTE = "Prueba EXPLORATORIA: no es una ronda preregistrada.";

const OPTIONS = {
  available: true, detail: null, note: NOTE, reserved_from: "2026-10-01", max_filters: 2,
  timeframes: ["1h", "4h"],
  triggers: [
    { id: "sfp", label: "SFP del HeatMap", exit: "native" },
    { id: "rf_flip", label: "Giro del Range Filter", exit: "native" },
  ],
  filters: [
    { id: "ema", label: "EMA 144" }, { id: "rf", label: "Range Filter" },
    { id: "wt", label: "WaveTrend" },
  ],
  symbols: ["BTCUSDT", "ETHUSDT"],
  series: [],
};

const SUMMARY = {
  trades: 40, winrate: 0.375, profit_factor: 0.93, net_pnl_usdt: -1.2, expectancy_usdt: -0.03,
  max_drawdown_pct: 4.2, avg_win_usdt: 0.8, avg_loss_usdt: -0.5, longs: 22, shorts: 18,
  close_reasons: { SL: 25, TP: 15 },
};

const RESULT = {
  exploratory: true, note: NOTE,
  params: { symbols: ["BTCUSDT"], timeframe: "1h", trigger: "sfp", filters: ["ema"],
            exit_mode: "native", name: "combo|sfp|ema|native" },
  period: { start: "2022-04-17", end: "2026-09-30", reserved_from: "2026-10-01" },
  result: SUMMARY,
  control: { ...SUMMARY, winrate: 0.35, trades: 41 },
  by_symbol: [{ key: "BTCUSDT", trades: 40, winrate: 0.375, profit_factor: 0.93, net_pnl_usdt: -1.2 }],
  by_year: [{ key: "2023", trades: 40, winrate: 0.375, profit_factor: 0.93, net_pnl_usdt: -1.2 }],
  skipped_by_risk_cap: 3, missing: [],
  engine: { margin_usdt: 5, leverage: 10, taker_fee_pct: 0.0006, slippage_bps: 5 },
  elapsed_s: 1.4,
};

afterEach(() => vi.unstubAllGlobals());

describe("IndicatorsTab", () => {
  it("dice como crear el archivo cuando no hay historial", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "/api/explorer/options": { status: 200, body: { ...OPTIONS, available: false,
        detail: "No hay archivo de historial. Crealo con scripts/download_history.py", symbols: [] } },
    }));
    render(withQueryClient(<IndicatorsTab />));
    expect(await screen.findByText(/download_history/)).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("EXPLORATORIA");
  });

  it("corre la prueba elegida y muestra el % de ganadoras y el control", async () => {
    const fetchMock = mockFetch({
      "/api/explorer/options": { status: 200, body: OPTIONS },
      "/api/explorer/run": { status: 200, body: RESULT },
    });
    vi.stubGlobal("fetch", fetchMock);
    render(withQueryClient(<IndicatorsTab />));
    await screen.findByText("Probar");
    fireEvent.click(screen.getByLabelText("EMA 144"));
    fireEvent.click(screen.getByLabelText("Range Filter"));
    expect(screen.getByLabelText("WaveTrend")).toBeDisabled();
    fireEvent.click(screen.getByText("Probar"));

    expect(await screen.findByText(/combo\|sfp\|ema\|native/)).toBeInTheDocument();
    expect(screen.getAllByText("37.5%").length).toBeGreaterThan(0);
    expect(screen.getByText("35.0%")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).startsWith("/api/explorer/run"));
    const q = new URL(String(call?.[0]), "http://x").searchParams;
    expect(q.getAll("symbols")).toEqual(["BTCUSDT"]);
    expect(q.getAll("filters")).toEqual(["ema", "rf"]);
    expect(q.get("timeframe")).toBe("1h");
    expect(q.get("trigger")).toBe("sfp");
    expect(q.get("start")).toBeNull();
  });
});
