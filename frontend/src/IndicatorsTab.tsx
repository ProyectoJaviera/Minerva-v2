import { useState } from "react";
import {
  ApiError,
  type ExplorerBreakdownRow,
  type ExplorerOptions,
  type ExplorerResult,
  type ExplorerSummary,
  useExplorerOptions,
  useExplorerRun,
} from "./api";
import { Card } from "./components/Card";
import { StatTile } from "./components/StatTile";
import { Unavailable } from "./components/Unavailable";
import { fmtNum, fmtPct, fmtPercentValue, fmtSigned } from "./format";

// Seccion «Indicadores» (v2): el dueno elige monedas, marco, un gatillo y hasta dos filtros, y ve al
// momento el % de operaciones ganadoras sobre el historial local de Bitunix. Es EXPLORATORIA: no es
// una ronda preregistrada, no se guarda y nunca usa velas desde la fecha reservada.

const inputCls =
  "rounded border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100";

function fmtPf(pf: number | null, trades: number): string {
  if (trades === 0) return "-";
  return pf === null ? "sin perdidas" : fmtNum(pf, 2);
}

function SummaryGrid({ s }: { s: ExplorerSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatTile label="% ganadoras" value={fmtPct(s.winrate)} />
      <StatTile label="Profit factor" value={fmtPf(s.profit_factor, s.trades)} />
      <StatTile label="Operaciones" value={`${s.trades} (${s.longs} L / ${s.shorts} S)`} />
      <StatTile label="PnL neto" value={`${fmtSigned(s.net_pnl_usdt, 2)} USDT`} />
      <StatTile label="Por operacion" value={fmtSigned(s.expectancy_usdt, 3)} />
      <StatTile label="Ganancia media" value={fmtSigned(s.avg_win_usdt, 3)} />
      <StatTile label="Perdida media" value={fmtSigned(s.avg_loss_usdt, 3)} />
      <StatTile label="Drawdown max." value={fmtPercentValue(s.max_drawdown_pct)} />
    </div>
  );
}

function BreakdownTable({ rows, caption, keyLabel }: { rows: ExplorerBreakdownRow[]; caption: string; keyLabel: string }) {
  if (rows.length === 0) return null;
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="mb-1 text-left text-sm text-gray-700 dark:text-gray-300">{caption}</caption>
        <thead>
          <tr className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
            <th className="py-1 pr-2 font-normal">{keyLabel}</th>
            <th className="py-1 pr-2 font-normal">Operaciones</th>
            <th className="py-1 pr-2 font-normal">% ganadoras</th>
            <th className="py-1 pr-2 font-normal">PF</th>
            <th className="py-1 pr-2 font-normal">PnL neto</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-gray-100 dark:border-gray-800">
              <td className="py-1 pr-2">{r.key}</td>
              <td className="py-1 pr-2">{r.trades}</td>
              <td className="py-1 pr-2">{fmtPct(r.winrate)}</td>
              <td className="py-1 pr-2">{fmtPf(r.profit_factor, r.trades)}</td>
              <td className="py-1 pr-2">{fmtSigned(r.net_pnl_usdt, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultCard({ r }: { r: ExplorerResult }) {
  const reasons = Object.entries(r.result.close_reasons)
    .map(([k, v]) => `${k} ${v}`)
    .join(" · ");
  return (
    <Card title={`Resultado exploratorio: ${r.params.name}`}>
      <p className="mb-3 text-sm text-gray-700 dark:text-gray-300">
        {r.params.symbols.join(", ")} · {r.params.timeframe} · periodo {r.period.start ?? "-"} a{" "}
        {r.period.end ?? "-"} · calculado en {fmtNum(r.elapsed_s, 1)} s{r.cached ? " (repetida: sale de la cache)" : ""}
      </p>
      <SummaryGrid s={r.result} />
      {reasons && <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">Cierres: {reasons}</p>}

      <h3 className="mt-4 text-sm font-semibold text-gray-700 dark:text-gray-300">
        Control: mismas velas y filtros, direccion al azar
      </h3>
      <p className="mb-2 text-xs text-gray-500 dark:text-gray-400">
        Si la combinacion no supera claramente a su control, el indicador no aporta informacion de
        direccion.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="% ganadoras" value={fmtPct(r.control.winrate)} />
        <StatTile label="Profit factor" value={fmtPf(r.control.profit_factor, r.control.trades)} />
        <StatTile label="Operaciones" value={String(r.control.trades)} />
        <StatTile label="PnL neto" value={`${fmtSigned(r.control.net_pnl_usdt, 2)} USDT`} />
      </div>

      <BreakdownTable rows={r.by_symbol} caption="Por moneda" keyLabel="Moneda" />
      <BreakdownTable rows={r.by_year} caption="Por ano (de entrada)" keyLabel="Ano" />

      {r.missing.length > 0 && (
        <ul className="mt-3 text-sm text-amber-800 dark:text-amber-300">
          {r.missing.map((m) => (
            <li key={m.symbol}>
              {m.symbol}: {m.reason}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
        Motor de la Fase 2: margen {r.engine.margin_usdt} USDT, {r.engine.leverage}x, comision{" "}
        {fmtPct(r.engine.taker_fee_pct, 2)} por lado, slippage {r.engine.slippage_bps} bps, entrada en el
        open de la vela siguiente. Entradas omitidas por tope de riesgo: {r.skipped_by_risk_cap}.
      </p>
    </Card>
  );
}

function Form({ opts }: { opts: ExplorerOptions }) {
  const run = useExplorerRun();
  const [symbols, setSymbols] = useState<string[]>(opts.symbols.slice(0, 1));
  const [timeframe, setTimeframe] = useState(opts.timeframes[0] ?? "1h");
  const [trigger, setTrigger] = useState(opts.triggers[0]?.id ?? "");
  const [filters, setFilters] = useState<string[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const toggle = (list: string[], id: string, max?: number) =>
    list.includes(id) ? list.filter((x) => x !== id) : max !== undefined && list.length >= max ? list : [...list, id];

  const errorText =
    run.error instanceof ApiError && run.error.detail
      ? run.error.detail
      : run.error
        ? "Error al correr la prueba."
        : null;

  return (
    <>
      <Card title="Probar indicadores (exploratorio)">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            run.mutate({ symbols, timeframe, trigger, filters, start: start || null, end: end || null });
          }}
        >
          <fieldset>
            <legend className="mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">Monedas</legend>
            <div className="flex flex-wrap gap-2">
              {opts.symbols.map((s) => (
                <label key={s} className="flex items-center gap-1 text-sm text-gray-800 dark:text-gray-200">
                  <input type="checkbox" checked={symbols.includes(s)} onChange={() => setSymbols(toggle(symbols, s))} />
                  {s}
                </label>
              ))}
              <button type="button" className="text-xs text-blue-700 underline dark:text-blue-400" onClick={() => setSymbols(opts.symbols)}>
                todas
              </button>
            </div>
          </fieldset>

          <div className="flex flex-wrap gap-4">
            <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
              Marco
              <select className={inputCls} value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                {opts.timeframes.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
              Gatillo (da la entrada y su direccion)
              <select className={inputCls} value={trigger} onChange={(e) => setTrigger(e.target.value)}>
                {opts.triggers.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
              Desde (opcional)
              <input type="date" className={inputCls} value={start} onChange={(e) => setStart(e.target.value)} />
            </label>
            <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
              Hasta (opcional, antes del {opts.reserved_from})
              <input type="date" className={inputCls} value={end} max={opts.reserved_from} onChange={(e) => setEnd(e.target.value)} />
            </label>
          </div>

          <fieldset>
            <legend className="mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">
              Filtros (hasta {opts.max_filters}; un largo exige estado alcista y un corto bajista)
            </legend>
            <div className="flex flex-wrap gap-3">
              {opts.filters.map((f) => (
                <label key={f.id} className="flex items-center gap-1 text-sm text-gray-800 dark:text-gray-200">
                  <input
                    type="checkbox"
                    checked={filters.includes(f.id)}
                    disabled={!filters.includes(f.id) && filters.length >= opts.max_filters}
                    onChange={() => setFilters(toggle(filters, f.id, opts.max_filters))}
                  />
                  {f.label}
                </label>
              ))}
            </div>
          </fieldset>

          <button
            type="submit"
            disabled={run.isPending || symbols.length === 0}
            className="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {run.isPending ? "Calculando..." : "Probar"}
          </button>
          {errorText && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-400">
              {errorText}
            </p>
          )}
        </form>
      </Card>
      {run.data && <ResultCard r={run.data} />}
    </>
  );
}

export function IndicatorsTab() {
  const options = useExplorerOptions();

  if (options.isLoading) {
    return <p className="text-sm text-gray-500">Cargando indicadores...</p>;
  }
  if (options.isError || !options.data) {
    return (
      <Card title="Indicadores">
        <Unavailable error={options.error} what="Indicadores" />
      </Card>
    );
  }
  const opts = options.data;
  return (
    <div className="space-y-4">
      <p
        role="note"
        className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-200"
      >
        {opts.note}
      </p>
      {opts.available ? (
        <Form opts={opts} />
      ) : (
        <Card title="Indicadores">
          <p role="status" className="text-sm text-gray-700 dark:text-gray-300">
            {opts.detail}
          </p>
        </Card>
      )}
    </div>
  );
}
