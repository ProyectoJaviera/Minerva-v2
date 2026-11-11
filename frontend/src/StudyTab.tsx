import { useState } from "react";
import { type StudyStats, type StudyStrategy, useStudyForward } from "./api";
import { Card } from "./components/Card";
import { StatTile } from "./components/StatTile";
import { Unavailable } from "./components/Unavailable";

// Pestana «Estudio» (v2): el estado de la prueba hacia adelante de las estrategias en estudio y el
// resumen de las rondas de investigacion. Todo es de solo lectura; el servidor calcula la prueba
// sobre el archivo de historial local (se actualiza cada 6 h con la tarea MinervaV2HistoryUpdate).

function fmtPf(pf: number | null): string {
  return pf === null ? "-" : pf.toFixed(2);
}

function fmtUsdt(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)} USDT`;
}

function fmtDate(iso?: string): string {
  return iso ? `${iso.slice(0, 16).replace("T", " ")} UTC` : "-";
}

function StatsRow({ title, stats }: { title: string; stats: StudyStats }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      <span className="text-xs font-medium text-gray-500 dark:text-gray-400 sm:self-center">{title}</span>
      <StatTile label="Operaciones" value={String(stats.trades)} />
      <StatTile label="PF" value={fmtPf(stats.pf)} />
      <StatTile label="Resultado" value={fmtUsdt(stats.pnl_usdt)} />
      <StatTile label="Ganadoras" value={stats.win_rate_pct === null ? "-" : `${stats.win_rate_pct}%`} />
    </div>
  );
}

const VERDICT_STYLE: Record<string, string> = {
  "en curso": "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
  "sigue en estudio": "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200",
  descartada: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200",
};

function StrategyCard({ s, reviewTrades }: { s: StudyStrategy; reviewTrades: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-3 rounded border border-gray-200 p-3 dark:border-gray-700">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{s.label}</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {s.origin}. Desde el {s.start} ({s.days} días).
          </p>
        </div>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${VERDICT_STYLE[s.review.verdict] ?? ""}`}>
          {s.review.verdict}
        </span>
      </div>
      <StatsRow title="Estrategia" stats={s.stats} />
      <StatsRow title="Control al azar" stats={s.control} />
      <p className="text-xs text-gray-500 dark:text-gray-400">
        {s.stats.trades} de {reviewTrades} operaciones para la revisión
        {s.open_trades > 0 ? `; ${s.open_trades} todavía abierta(s), con el resultado al último precio` : ""}.
      </p>
      {s.trade_list.length > 0 && (
        <div>
          <button
            onClick={() => setOpen(!open)}
            className="text-xs font-medium text-blue-700 hover:underline dark:text-blue-300"
          >
            {open ? "Ocultar operaciones" : `Ver operaciones (${s.trade_list.length})`}
          </button>
          {open && (
            <div className="mt-2 overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead className="text-left text-gray-500 dark:text-gray-400">
                  <tr>
                    <th className="pr-3">Entrada (UTC)</th>
                    <th className="pr-3">Moneda</th>
                    <th className="pr-3">Lado</th>
                    <th className="pr-3">Precio entrada</th>
                    <th className="pr-3">Precio salida</th>
                    <th className="pr-3">Cierre</th>
                    <th className="pr-3 text-right">Resultado</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums text-gray-800 dark:text-gray-200">
                  {s.trade_list.map((t) => (
                    <tr key={`${t.symbol}-${t.entry_time}`}>
                      <td className="pr-3">{t.entry_time.slice(0, 16).replace("T", " ")}</td>
                      <td className="pr-3">{t.symbol}</td>
                      <td className="pr-3">{t.side === "LONG" ? "Largo" : "Corto"}</td>
                      <td className="pr-3">{t.entry_price}</td>
                      <td className="pr-3">{t.exit_price}</td>
                      <td className="pr-3">{t.close_reason === "END_OF_DATA" ? "abierta" : t.close_reason}</td>
                      <td className="pr-3 text-right">{fmtUsdt(t.pnl_usdt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ForwardCard() {
  const query = useStudyForward();
  if (query.isLoading) return <p className="text-sm text-gray-500">Cargando el estudio...</p>;
  if (query.isError || !query.data) {
    return (
      <Card title="Prueba hacia adelante">
        <Unavailable error={query.error} what="Prueba hacia adelante" />
      </Card>
    );
  }
  const { status, detail, result } = query.data;
  return (
    <Card title="Prueba hacia adelante">
      <p className="mb-3 text-sm text-gray-700 dark:text-gray-300">
        Estrategias congeladas que se repiten sobre las velas nuevas y solo cuentan las operaciones abiertas después
        de su fecha de inicio: equivale a operarlas en paper. Cada una se compara con su versión con dirección al
        azar. Se evalúa una sola vez, al llegar a {result?.review?.trades ?? 60} operaciones o el{" "}
        {result?.review?.date ?? "2027-05-10"}: sigue en estudio solo con PF de {result?.review?.min_pf ?? 1.2} o más y
        por encima de su control.
      </p>
      {status === "missing" && (
        <p role="status" className="text-sm text-gray-700 dark:text-gray-300">
          {detail}
        </p>
      )}
      {status === "error" && (
        <p role="alert" className="text-sm text-red-800 dark:text-red-300">
          No se pudo calcular la prueba: {detail}
        </p>
      )}
      {status === "computing" && (
        <p role="status" className="mb-3 text-sm text-gray-500 dark:text-gray-400">
          Calculando con las velas más recientes (tarda alrededor de un minuto)...
        </p>
      )}
      {result && !result.available && <p className="text-sm text-gray-700 dark:text-gray-300">{result.detail}</p>}
      {result?.available && (
        <div className="space-y-3">
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Datos hasta {fmtDate(result.data_until)}. Calculado {fmtDate(result.computed_at)}.
          </p>
          {result.stale_symbols && result.stale_symbols.length > 0 && (
            <p role="alert" className="text-xs text-amber-800 dark:text-amber-300">
              Monedas con datos atrasados (no se cuentan desde entonces): {result.stale_symbols.join(", ")}
            </p>
          )}
          {result.strategies?.map((s) => (
            <StrategyCard key={s.name} s={s} reviewTrades={result.review?.trades ?? 60} />
          ))}
        </div>
      )}
    </Card>
  );
}

function RoundsCard() {
  const query = useStudyForward();
  if (!query.data) return null;
  return (
    <Card title="Rondas de investigación">
      <ol className="space-y-3">
        {query.data.rounds.map((r) => (
          <li key={r.id} className="text-sm">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-semibold text-gray-900 dark:text-gray-100">{r.title}</span>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {r.date} · pasan {r.passed} de {r.total}
              </span>
            </div>
            <p className="text-gray-600 dark:text-gray-300">Qué se probó: {r.tested}.</p>
            <p className="text-gray-800 dark:text-gray-200">{r.result}</p>
            <p className="text-xs text-gray-500 dark:text-gray-400">Informe: {r.doc}</p>
          </li>
        ))}
      </ol>
      <p className="mt-4 rounded bg-gray-50 p-3 text-sm text-gray-800 dark:bg-gray-900/40 dark:text-gray-200">
        {query.data.conclusion}
      </p>
    </Card>
  );
}

export function StudyTab() {
  return (
    <div className="space-y-4">
      <ForwardCard />
      <RoundsCard />
    </div>
  );
}
