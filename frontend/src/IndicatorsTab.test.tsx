import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IndicatorsTab } from "./IndicatorsTab";
import { mockFetch, withQueryClient } from "./testUtils";

const NOTE = "Prueba EXPLORATORIA: no es una ronda preregistrada.";

const OPTIONS = {
  available: true, detail: null, note: NOTE,
  timeframes: [
    { id: "15m", label: "15m" }, { id: "1h", label: "1h" }, { id: "4h", label: "4h" },
    { id: "1d", label: "1D" }, { id: "1w", label: "1S" },
  ],
  indicators: [
    { id: "sfp", label: "SFP del HeatMap", kind: "evento" },
    { id: "fvg", label: "FVG", kind: "evento" },
    { id: "rf", label: "Range Filter", kind: "estado" },
    { id: "ema", label: "EMA 144", kind: "estado" },
  ],
  exits: [
    { id: "s2_tp2r", label: "SL 2 ATR, TP 2R" }, { id: "s3_trail3", label: "SL 3 ATR con trailing de 3 ATR" },
    { id: "pct", label: "Personalizada en % (SL, TP y trailing)" },
  ],
  default_exit: "s2_tp2r",
  pct_limits: { sl: 50, tp: 500, trail: 50 },
  max_sl_pct_before_skip: 5,
  window: { default: 5, max: 50 },
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
  params: { symbols: ["BTCUSDT"], timeframe: "1d", indicators: ["sfp", "fvg", "rf", "ema"], window: 5,
            exit: "s3_trail3", exit_label: "SL 3 ATR con trailing de 3 ATR", min_agree: 3, name: "mix|sfp+fvg+rf+ema|w5|s3_trail3" },
  period: { start: "2022-04-17", end: "2026-09-30" },
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
        detail: "No hay archivo de historial. Crealo con scripts/update_history_file.py", symbols: [] } },
    }));
    render(withQueryClient(<IndicatorsTab />));
    expect(await screen.findByText(/update_history_file/)).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("EXPLORATORIA");
  });

  it("todos los indicadores son casillas, uno por linea, y sin elegir ninguno no deja probar", async () => {
    vi.stubGlobal("fetch", mockFetch({ "/api/explorer/options": { status: 200, body: OPTIONS } }));
    render(withQueryClient(<IndicatorsTab />));
    await screen.findByText("Probar en 1h");
    for (const label of ["SFP del HeatMap", "FVG", "Range Filter", "EMA 144"]) {
      expect(screen.getByLabelText(new RegExp(label))).toHaveAttribute("type", "checkbox");
    }
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByText("Probar en 1h")).toBeDisabled();
    expect(screen.getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual([
      "15m", "1h", "4h", "1d", "1w",
    ]);
  });

  it("corre con todos los indicadores, la temporalidad y la salida elegidas", async () => {
    const fetchMock = mockFetch({
      "/api/explorer/options": { status: 200, body: OPTIONS },
      "/api/explorer/run": { status: 200, body: RESULT },
    });
    vi.stubGlobal("fetch", fetchMock);
    render(withQueryClient(<IndicatorsTab />));
    await screen.findByText("Probar en 1h");
    fireEvent.click(screen.getByText("todos"));
    fireEvent.click(screen.getByLabelText("1D"));
    fireEvent.change(screen.getByLabelText("Salida"), { target: { value: "s3_trail3" } });
    fireEvent.change(screen.getByLabelText(/Deben coincidir/), { target: { value: "3" } });
    fireEvent.click(screen.getByText("Probar en 1D"));

    expect(await screen.findByText(/4 indicadores \(coinciden al menos 3\): SFP del HeatMap \+ FVG \+ Range Filter \+ EMA 144/)).toBeInTheDocument();
    expect(screen.getAllByText("37.5%").length).toBeGreaterThan(0);
    expect(screen.getByText("35.0%")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).startsWith("/api/explorer/run"));
    const q = new URL(String(call?.[0]), "http://x").searchParams;
    expect(q.getAll("indicators")).toEqual(["sfp", "fvg", "rf", "ema"]);
    expect(q.getAll("symbols")).toEqual(["BTCUSDT"]);
    expect(q.get("timeframe")).toBe("1d");
    expect(q.get("exit")).toBe("s3_trail3");
    expect(q.get("window")).toBe("5");
    expect(q.get("min_agree")).toBe("3");
    expect(q.get("start")).toBeNull();
  });
});

describe("IndicatorsTab: salida en porcentaje", () => {
  it("manda SL, TP y trailing en % y avisa si el SL es demasiado amplio", async () => {
    const fetchMock = mockFetch({
      "/api/explorer/options": { status: 200, body: OPTIONS },
      "/api/explorer/run": { status: 200, body: RESULT },
    });
    vi.stubGlobal("fetch", fetchMock);
    render(withQueryClient(<IndicatorsTab />));
    await screen.findByText("Probar en 1h");
    expect(screen.queryByLabelText("SL %")).toBeNull();
    fireEvent.change(screen.getByLabelText("Salida"), { target: { value: "pct" } });
    fireEvent.change(screen.getByLabelText("SL %"), { target: { value: "7" } });
    expect(screen.getByRole("alert")).toHaveTextContent("omitira");
    fireEvent.change(screen.getByLabelText("SL %"), { target: { value: "1,5" } });
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.change(screen.getByLabelText("TP % (opcional)"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Trailing % (opcional)"), { target: { value: "0.8" } });
    fireEvent.click(screen.getByLabelText(/EMA 144/));
    fireEvent.click(screen.getByText("Probar en 1h"));
    await screen.findByText("Resultado exploratorio");
    const call = fetchMock.mock.calls.find(([url]) => String(url).startsWith("/api/explorer/run"));
    const q = new URL(String(call?.[0]), "http://x").searchParams;
    expect(q.get("exit")).toBe("pct");
    expect(q.get("sl_pct")).toBe("1.5");
    expect(q.get("tp_pct")).toBeNull();
    expect(q.get("trail_pct")).toBe("0.8");
  });
});

describe("IndicatorsTab: entradas omitidas por el tope de riesgo", () => {
  it("avisa cuando el motor omitio entradas por un SL demasiado amplio", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "/api/explorer/options": { status: 200, body: OPTIONS },
      "/api/explorer/run": { status: 200, body: { ...RESULT, skipped_by_risk_cap: 72 } },
    }));
    render(withQueryClient(<IndicatorsTab />));
    await screen.findByText("Probar en 1h");
    fireEvent.click(screen.getByLabelText(/EMA 144/));
    fireEvent.click(screen.getByText("Probar en 1h"));
    expect(await screen.findByText(/72 entradas omitidas/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("5 % del precio");
  });
});
