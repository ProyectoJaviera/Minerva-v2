import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StudyTab } from "./StudyTab";
import { mockFetch, withQueryClient } from "./testUtils";

const ROUNDS = [
  {
    id: "ronda4", date: "2026-11-11", title: "Ronda 4: fuerza relativa, squeeze y volumen",
    doc: "docs/v2/RONDA4_V2.md", tested: "21 senales en 4h", result: "Ninguna pasa.", passed: 0, total: 21,
  },
];
const CONCLUSION = "Ninguna regla muestra ventaja. Nada de esto habilita dinero real.";

const STATS = { trades: 2, pf: 0.75, pnl_usdt: -0.07, win_rate_pct: 50 };
const CONTROL = { trades: 3, pf: 0.48, pnl_usdt: -0.21, win_rate_pct: 33.3 };

const READY = {
  status: "ready", rounds: ROUNDS, conclusion: CONCLUSION,
  result: {
    available: true, data_until: "2026-11-11T08:00:00+00:00", computed_at: "2026-11-11T09:00:00+00:00",
    stale_symbols: ["ZECUSDT"], review: { trades: 60, date: "2027-05-10", min_pf: 1.2 },
    strategies: [
      {
        name: "r3|fvg|ema|s3_trail3|limit", label: "FVG + EMA 144", origin: "Finalista de la ronda 3",
        start: "2026-11-10", days: 1.3, stats: STATS, control: CONTROL,
        review: { due: false, verdict: "en curso" }, open_trades: 1,
        trade_list: [
          {
            entry_time: "2026-11-10T12:00:00+00:00", exit_time: "2026-11-11T08:00:00+00:00", symbol: "TRXUSDT",
            side: "SHORT", entry_price: 0.31916, exit_price: 0.31737, close_reason: "END_OF_DATA", pnl_usdt: 0.2,
          },
        ],
      },
    ],
  },
};

afterEach(() => vi.unstubAllGlobals());

describe("StudyTab", () => {
  it("muestra cada estrategia con su control, la revision y las rondas", async () => {
    vi.stubGlobal("fetch", mockFetch({ "/api/study/forward": { status: 200, body: READY } }));
    render(withQueryClient(<StudyTab />));
    expect(await screen.findByText("FVG + EMA 144")).toBeInTheDocument();
    expect(screen.getByText("en curso")).toBeInTheDocument();
    expect(screen.getByText("Control al azar")).toBeInTheDocument();
    expect(screen.getByText("0.75")).toBeInTheDocument();
    expect(screen.getByText("0.48")).toBeInTheDocument();
    expect(screen.getByText(/2 de 60 operaciones/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("ZECUSDT");
    expect(screen.getByText("Ronda 4: fuerza relativa, squeeze y volumen")).toBeInTheDocument();
    expect(screen.getByText(/pasan 0 de 21/)).toBeInTheDocument();
    expect(screen.getByText(CONCLUSION)).toBeInTheDocument();
  });

  it("lista las operaciones al pedirlas", async () => {
    vi.stubGlobal("fetch", mockFetch({ "/api/study/forward": { status: 200, body: READY } }));
    render(withQueryClient(<StudyTab />));
    fireEvent.click(await screen.findByText("Ver operaciones (1)"));
    expect(screen.getByText("TRXUSDT")).toBeInTheDocument();
    expect(screen.getByText("Corto")).toBeInTheDocument();
    expect(screen.getByText("abierta")).toBeInTheDocument();
  });

  it("avisa mientras calcula y cuando no hay archivo de historial", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "/api/study/forward": { status: 200, body: { status: "computing", result: null, rounds: ROUNDS, conclusion: CONCLUSION } },
    }));
    const { unmount } = render(withQueryClient(<StudyTab />));
    expect(await screen.findByText(/Calculando con las velas/)).toBeInTheDocument();
    unmount();
    vi.stubGlobal("fetch", mockFetch({
      "/api/study/forward": {
        status: 200,
        body: { status: "missing", detail: "No hay archivo de historial. Crealo con scripts/update_history_file.py.",
          rounds: ROUNDS, conclusion: CONCLUSION },
      },
    }));
    render(withQueryClient(<StudyTab />));
    expect(await screen.findByText(/update_history_file/)).toBeInTheDocument();
  });
});
