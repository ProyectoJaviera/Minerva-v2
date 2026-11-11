import { useState } from "react";
import {
  ApiError,
  type ExplorerBreakdownRow,
  type ExplorerOptions,
  type ExplorerResult,
  type ExplorerSummary,
  useDataStatus,
  useExplorerOptions,
  useExplorerRun,
} from "./api";
import { Card } from "./components/Card";
import { StatTile } from "./components/StatTile";
import { Unavailable } from "./components/Unavailable";
import { fmtAgo, fmtCompact, fmtNum, fmtPct, fmtPercentValue, fmtSigned } from "./format";

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

function ResultCard({ r, labels }: { r: ExplorerResult; labels: ExplorerOptions }) {
  const reasons = Object.entries(r.result.close_reasons)
    .map(([k, v]) => `${k} ${v}`)
    .join(" · ");
  const names = r.params.indicators.map((id) => labels.indicators.find((i) => i.id === id)?.label ?? id);
  const tf = labels.timeframes.find((t) => t.id === r.params.timeframe)?.label ?? r.params.timeframe;
  return (
    <Card title="Resultado exploratorio">
      <p className="mb-1 text-sm font-medium text-gray-800 dark:text-gray-200">
        {names.length} indicador{names.length === 1 ? "" : "es"}
        {r.params.min_agree < names.length ? ` (coinciden al menos ${r.params.min_agree})` : ""}: {names.join(" + ")}
      </p>
      <p className="mb-3 text-sm text-gray-700 dark:text-gray-300">
        {r.params.symbols.join(", ")} · {tf} · {r.params.exit_label} · ventana {r.params.window} · periodo {r.period.start ?? "-"} a{" "}
        {r.period.end ?? "-"} · calculado en {fmtNum(r.elapsed_s, 1)} s{r.cached ? " (repetida: sale de la cache)" : ""}
      </p>
      {r.skipped_by_risk_cap > 0 && (
        <p
          role="alert"
          className="mb-3 rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-200"
        >
          {r.skipped_by_risk_cap} entrada{r.skipped_by_risk_cap === 1 ? "" : "s"} omitida
          {r.skipped_by_risk_cap === 1 ? "" : "s"} porque su SL perdia mas margen del permitido (a{" "}
          {r.engine.leverage}x, un SL mayor que {labels.max_sl_pct_before_skip} % del precio). Pasa en marcos largos
          con SL en ATR: en 1D y 1S usa la salida en % con un SL de hasta {labels.max_sl_pct_before_skip} %.
        </p>
      )}
      <SummaryGrid s={r.result} />
      {reasons && <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">Cierres: {reasons}</p>}

      <h3 className="mt-4 text-sm font-semibold text-gray-700 dark:text-gray-300">
        Control: mismas velas de entrada y misma salida, direccion al azar
      </h3>
      <p className="mb-2 text-xs text-gray-500 dark:text-gray-400">
        Si la combinacion no supera claramente a su control, los indicadores no aportan informacion
        de direccion.
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
  const [timeframe, setTimeframe] = useState(
    opts.timeframes.find((t) => t.id === "1h")?.id ?? opts.timeframes[0]?.id ?? "1h",
  );
  const [indicators, setIndicators] = useState<string[]>([]);
  const [windowBars, setWindowBars] = useState(opts.window.default);
  const [exit, setExit] = useState(opts.default_exit);
  // 0 = todos los marcados deben coincidir
  const [minAgree, setMinAgree] = useState(0);
  // salida en %: texto libre ("" = sin ese nivel); el SL es obligatorio
  const [slPct, setSlPct] = useState("2");
  const [tpPct, setTpPct] = useState("4");
  const [trailPct, setTrailPct] = useState("");
  const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")));
  const slTooWide = exit === "pct" && (num(slPct) ?? 0) > opts.max_sl_pct_before_skip;
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const toggle = (list: string[], id: string) =>
    list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
  const hasEvent = opts.indicators.some((i) => i.kind === "evento" && indicators.includes(i.id));
  const tfLabel = (id: string) => opts.timeframes.find((t) => t.id === id)?.label ?? id;

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
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            run.mutate({
              symbols,
              timeframe,
              indicators,
              window: windowBars,
              exit,
              minAgree: minAgree > 0 && minAgree < indicators.length ? minAgree : null,
              slPct: num(slPct),
              tpPct: num(tpPct),
              trailPct: num(trailPct),
              start: start || null,
              end: end || null,
            });
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

          <fieldset>
            <legend className="mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">Temporalidad</legend>
            <div className="flex flex-wrap gap-3">
              {opts.timeframes.map((t) => (
                <label key={t.id} className="flex items-center gap-1 text-sm text-gray-800 dark:text-gray-200">
                  <input
                    type="radio"
                    name="timeframe"
                    value={t.id}
                    checked={timeframe === t.id}
                    onChange={() => setTimeframe(t.id)}
                  />
                  {t.label}
                </label>
              ))}
            </div>
            {timeframe === "15m" && (
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                15m tiene 4 veces mas velas que 1h: con varias monedas puede tardar minutos.
              </p>
            )}
            {timeframe === "1w" && (
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Desde 2022 hay pocas velas semanales: espera pocas operaciones.
              </p>
            )}
          </fieldset>

          <fieldset>
            <legend className="mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">
              Indicadores (marca uno o varios: se entra cuando todos coinciden; largo si todos son
              alcistas, corto si todos son bajistas)
            </legend>
            <div className="mb-1 flex gap-3">
              <button
                type="button"
                className="text-xs text-blue-700 underline dark:text-blue-400"
                onClick={() => setIndicators(opts.indicators.map((i) => i.id))}
              >
                todos
              </button>
              <button type="button" className="text-xs text-blue-700 underline dark:text-blue-400" onClick={() => setIndicators([])}>
                ninguno
              </button>
            </div>
            <ul className="divide-y divide-gray-100 dark:divide-gray-700">
              {opts.indicators.map((i) => (
                <li key={i.id} className="py-1">
                  <label className="flex items-center gap-2 text-sm text-gray-800 dark:text-gray-200">
                    <input type="checkbox" checked={indicators.includes(i.id)} onChange={() => setIndicators(toggle(indicators, i.id))} />
                    <span className="flex-1">{i.label}</span>
                    <span
                      className={
                        "rounded px-1.5 text-xs " +
                        (i.kind === "evento"
                          ? "bg-blue-50 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200"
                          : "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200")
                      }
                    >
                      {i.kind}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Los de estado votan en cada vela; los de evento votan solo durante la ventana desde su senal.
            </p>
          </fieldset>

          <div className="flex flex-wrap gap-4">
            <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
              Deben coincidir
              <select
                className={inputCls}
                value={minAgree > 0 && minAgree < indicators.length ? minAgree : 0}
                disabled={indicators.length < 2}
                onChange={(e) => setMinAgree(Number(e.target.value))}
              >
                <option value={0}>todos ({indicators.length})</option>
                {Array.from({ length: Math.max(0, indicators.length - 1) }, (_, k) => k + 1)
                  .reverse()
                  .map((k) => (
                    <option key={k} value={k}>
                      al menos {k}
                    </option>
                  ))}
              </select>
            </label>
            <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
              Ventana de los eventos (velas)
              <input
                type="number"
                min={1}
                max={opts.window.max}
                className={inputCls + " w-24"}
                value={windowBars}
                disabled={!hasEvent}
                onChange={(e) => setWindowBars(Math.max(1, Math.min(opts.window.max, Number(e.target.value) || 1)))}
              />
            </label>
            <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
              Salida
              <select className={inputCls} value={exit} onChange={(e) => setExit(e.target.value)}>
                {opts.exits.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.label}
                  </option>
                ))}
              </select>
            </label>
            {exit === "pct" && (
              <>
                <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
                  SL %
                  <input type="text" inputMode="decimal" className={inputCls + " w-20"} value={slPct} onChange={(e) => setSlPct(e.target.value)} />
                </label>
                <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
                  TP % (opcional)
                  <input type="text" inputMode="decimal" className={inputCls + " w-20"} value={tpPct} onChange={(e) => setTpPct(e.target.value)} />
                </label>
                <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
                  Trailing % (opcional)
                  <input type="text" inputMode="decimal" className={inputCls + " w-20"} value={trailPct} onChange={(e) => setTrailPct(e.target.value)} />
                </label>
              </>
            )}
            <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
              Desde (opcional)
              <input type="date" className={inputCls} value={start} onChange={(e) => setStart(e.target.value)} />
            </label>
            <label className="flex flex-col text-sm text-gray-700 dark:text-gray-300">
              Hasta (opcional)
              <input type="date" className={inputCls} value={end} onChange={(e) => setEnd(e.target.value)} />
            </label>
          </div>
          {exit === "pct" && (
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Porcentajes del precio de entrada (no del margen). Sin TP ni trailing, el motor usa su TP de
              respaldo del 10 %. El trailing sigue al mejor precio a esa distancia.
            </p>
          )}
          {slTooWide && (
            <p role="alert" className="text-sm text-amber-800 dark:text-amber-300">
              Con este apalancamiento, un SL mayor que {opts.max_sl_pct_before_skip} % perderia mas margen del permitido:
              el motor omitira esas entradas.
            </p>
          )}

          <button
            type="submit"
            disabled={run.isPending || symbols.length === 0 || indicators.length === 0}
            className="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {run.isPending ? "Calculando..." : `Probar en ${tfLabel(timeframe)}`}
          </button>
          {errorText && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-400">
              {errorText}
            </p>
          )}
        </form>
      </Card>
      {run.data && <ResultCard r={run.data} labels={opts} />}
    </>
  );
}

function Freshness({ label, block, extra }: { label: string; block?: { last_at: string | null; stale: boolean }; extra?: string }) {
  const value = block?.last_at ? fmtAgo(block.last_at) : "sin datos";
  return (
    <div className="flex flex-col">
      <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
      <span
        className={
          "tabular-nums text-base font-medium " +
          (block && !block.stale ? "text-gray-900 dark:text-gray-100" : "text-amber-700 dark:text-amber-300")
        }
      >
        {value}
        {block?.stale ? " (atrasado)" : ""}
      </span>
      {extra && <span className="text-xs text-gray-500 dark:text-gray-400">{extra}</span>}
    </div>
  );
}

// Si las tareas programadas de captura (MinervaV2*) estan funcionando: ultima foto de cada cosa,
// errores y los ultimos valores del libro de ordenes. No muestra resultados de ninguna estrategia.
function DataStatusCard() {
  const status = useDataStatus();
  if (status.isLoading) return <p className="text-sm text-gray-500">Cargando datos capturados...</p>;
  if (status.isError || !status.data) {
    return (
      <Card title="Datos capturados">
        <Unavailable error={status.error} what="Datos capturados" />
      </Card>
    );
  }
  const { market, history } = status.data;
  return (
    <Card title="Datos capturados">
      {!market.available ? (
        <p role="status" className="text-sm text-gray-700 dark:text-gray-300">
          Todavia no hay datos capturados ({market.path}). Se llenan solos con las tareas programadas MinervaV2
          (scriptsegister_v2_data_tasks.ps1).
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Freshness
              label="Libro de ordenes (cada 5 min)"
              block={market.orderbook}
              extra={`${market.orderbook?.snapshots_24h ?? 0} fotos en 24 h, ${market.orderbook?.symbols_24h ?? 0} monedas`}
            />
            <Freshness label="Funding (cada hora)" block={market.funding} extra={`${market.funding?.symbols ?? 0} monedas`} />
            <Freshness
              label="Fear & Greed (diario)"
              block={market.feargreed}
              extra={market.feargreed?.value != null ? `${market.feargreed.value} (${market.feargreed.classification ?? "-"})` : undefined}
            />
            <Freshness
              label="Historial de velas (cada 6 h)"
              block={history.available ? history : undefined}
              extra={history.available ? "ultima vela de 1h" : "sin archivo de historial"}
            />
          </div>
          {(market.errors_24h?.count ?? 0) > 0 && (
            <p role="alert" className="mt-2 text-sm text-amber-800 dark:text-amber-300">
              {market.errors_24h?.count} captura(s) con error en 24 h. Ultimo: {market.errors_24h?.last?.kind}{" "}
              {market.errors_24h?.last?.detail}
            </p>
          )}
          {market.symbols && market.symbols.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="mb-1 text-left text-sm text-gray-700 dark:text-gray-300">
                  Ultima foto del libro por moneda (50 niveles por lado)
                </caption>
                <thead>
                  <tr className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
                    <th className="py-1 pr-2 font-normal">Moneda</th>
                    <th className="py-1 pr-2 font-normal">Precio medio</th>
                    <th className="py-1 pr-2 font-normal">Spread (pb)</th>
                    <th className="py-1 pr-2 font-normal">Desequilibrio 20 niveles</th>
                    <th className="py-1 pr-2 font-normal">Compras / ventas (USDT)</th>
                    <th className="py-1 pr-2 font-normal">Funding (Bitunix)</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {market.symbols.map((r) => (
                    <tr key={r.symbol} className="border-b border-gray-100 dark:border-gray-800">
                      <td className="py-1 pr-2">{r.symbol}</td>
                      <td className="py-1 pr-2">{fmtNum(r.mid, 6)}</td>
                      <td className="py-1 pr-2">{fmtNum(r.spread_bps, 2)}</td>
                      <td className="py-1 pr-2">{fmtSigned(r.imbalance_20, 2)}</td>
                      <td className="py-1 pr-2">
                        {fmtCompact(r.bid_notional_50)} / {fmtCompact(r.ask_notional_50)}
                      </td>
                      <td className="py-1 pr-2">{fmtNum(r.funding_rate, 6)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Desequilibrio: (compras - ventas) / (compras + ventas) en los 20 primeros niveles; positivo = mas compras.
              </p>
            </div>
          )}
        </>
      )}
    </Card>
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
      <DataStatusCard />
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
