# Minerva v2: investigación de indicadores técnicos y del filtro de IA (paper trading)

![Licencia MIT](https://img.shields.io/badge/licencia-MIT-green)
![Python 3.11 y 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![Solo paper trading](https://img.shields.io/badge/modo-solo%20paper%20trading-orange)
![Estado experimental](https://img.shields.io/badge/estado-experimental-yellow)

> ## ⚠ Aviso: solo paper trading, experimental y no es asesoría financiera
>
> **Minerva nunca envía órdenes reales.** Es 100 % *paper trading*: usa solo datos públicos de mercado de Bitunix y
> simula las operaciones localmente. Es un proyecto de investigación **experimental**, **no es asesoría financiera** ni
> una recomendación de inversión. El trading de futuros apalancados (real o simulado) **puede perder dinero** y nada de
> lo que hay aquí garantiza ganancias: que el simulador gane no implica que una cuenta real ganaría, porque la
> ejecución real tiene latencia, comisiones, deslizamiento y límites que el simulador solo aproxima
> ([lo que no se pudo verificar](docs/COSTOS_Y_LIMITES.md#lo-no-verificado)).

> ## Esta es la versión 2
>
> La v2 **parte de la etiqueta `v1.0`** del repositorio Minerva-v1 (el mismo código y el mismo historial). La medición ciega
> de la v1 sigue su curso **en ese otro repositorio**, con su propio bot; la v2 es donde continúa el desarrollo nuevo.
> Para que nada de la v2 pueda tocar el bot vivo de la v1, **todos sus nombres cambian**: proyecto y contenedor
> `minerva-v2`, imagen `minerva-v2:local`, volúmenes `minerva-v2_data` y `minerva-v2_logs`, puerto `8001` (el `8000` es de la v1),
> tareas programadas con prefijo `MinervaV2` y marca `MIGRADO_A_DOCKER_V2.txt`. Además arranca **sin** etiquetado del LLM,
> Telegram, brazo ejecutado, noticias ni avisos (`MINERVA_REAL_BOT=false` por defecto). **Nunca copies el `.env` real de la
> v1 a la v2.**

## Qué es

Minerva es un bot de investigación de trading de futuros cripto, **100 % paper trading**. Tiene dos partes:

- **Lo heredado de la v1:** en cada cierre de vela evalúa un universo dinámico de las principales criptomonedas con seis
  estrategias por reglas; cada señal se simula como una *operación sombra* que Claude (Anthropic) puede etiquetar
  `APROBADA` o `RECHAZADA` con un prompt **congelado**, y una cuenta de papel opera solo las aprobadas a través de un
  motor de riesgo. En la v1 sirve para medir, a ciegas, si el filtro de IA aporta valor; en la v2 está apagado por
  defecto.
- **Lo nuevo de la v2:** la **investigación de indicadores técnicos** (los de PunkAlgo HeatMap y Frost Trader
  reimplementados, más FVG, fuerza relativa, volumen y otros) con preregistros, controles al azar y los mismos criterios
  de la Fase 2; la pestaña **Indicadores** del dashboard para probar combinaciones a mano sobre el historial local; y la
  **captura de datos hacia adelante** (libro de órdenes, funding y Fear & Greed) con tareas programadas.

Incluye un simulador con comisiones, funding, deslizamiento y liquidación, un dashboard web, un bot de Telegram y todo
empaquetado en Docker.

## El problema que investiga

> Si un modelo de lenguaje revisa cada señal técnica y decide aprobarla o rechazarla, ¿mejora el resultado medio por
> operación frente a operar todas las señales sin filtrar?

Para responderlo sin engañarse, el diseño es deliberadamente estricto: cada señal se simula como una **sombra** (así existe
el contrafactual de las rechazadas), el prompt y el modelo se **congelan** y se vigilan con un hash, el análisis cuenta
**conglomerados** de operaciones solapadas en vez de operaciones, el veredicto se calcula **una sola vez**, con un
**placebo** de calibración previo, y **ningún canal muestra resultados** hasta que exista el registro oficial del veredicto.
Explicado paso a paso y sin jerga: [Metodología](docs/METODOLOGIA.md).

### Estado actual

- **Investigación de indicadores de la v2: ninguna estrategia pasó los criterios.** Ni los tres candidatos del
  [preregistro](docs/v2/PREREGISTRO_V2.md) ([resultado](docs/v2/RESULTADO_FASE2_V2.md)), ni las 176 combinaciones de la
  [exploración](docs/v2/EXPLORACION_V2.md), ni las rondas [3](docs/v2/RONDA3_V2.md) y [4](docs/v2/RONDA4_V2.md). Los tres
  finalistas de la ronda 3 perdieron en los datos reservados; la fuerza relativa semanal es la idea más estable.
- **Prueba hacia adelante en curso:** esos tres finalistas y la fuerza relativa semanal se siguen en paper desde el
  2026-11-10/11 con un criterio de revisión fijado de antemano ([detalle](docs/v2/PAPER_V2_RONDA3.md)).
- **Captura de datos en curso:** libro de órdenes cada 5 minutos, funding cada hora y Fear & Greed diario, para tener
  historial propio de lo que no se consigue gratis hacia atrás.
- **Medición del valor del LLM (v1): en curso, ciega, en el otro repositorio.** El veredicto se espera para comienzos
  de 2027 y es lo que más pesa para el rumbo de la v2.
- **Las seis estrategias por reglas de la v1 tampoco mostraron ventaja** en su backtest; se usan como generadores de
  señales, no como estrategias rentables.
- **No hay base para pasar a dinero real.** Y esta versión no tiene ejecución real: solo una interfaz documentada y desactivada.

## Cómo funciona

```mermaid
flowchart LR
    subgraph datos["Datos públicos y gratuitos"]
        CG["CoinGecko<br/>ranking"]
        BX["Bitunix<br/>velas y funding"]
    end
    CG --> U["Universo<br/>10 monedas"]
    BX --> S["6 estrategias<br/>por reglas"]
    U --> S
    S --> SH["Operación sombra<br/>por cada señal"]
    SH --> L["Claude etiqueta<br/>APROBADA o RECHAZADA<br/>prompt congelado"]
    L --> A["Cuenta paper<br/>solo las aprobadas<br/>con motor de riesgo"]
    L --> VD["Veredicto único<br/>300 conglomerados por lado"]
    SH --> VD
    A --> M["Monitor<br/>SL, TP, trailing, liquidación"]
```

Todo corre en **un solo proceso** (FastAPI + asyncio) con una base SQLite, y expone una API con login, un dashboard web y
un bot de Telegram. Detalle de componentes, flujo y decisiones de diseño: [Arquitectura](docs/ARQUITECTURA.md).

El diagrama es el bot heredado de la v1. Lo nuevo de la v2 corre aparte del bot: la investigación y la pestaña
Indicadores usan el motor de backtest sin red sobre un archivo de historial local (`history/history_v2.db`), y la captura
de datos son scripts que lanzan las tareas programadas `MinervaV2*` (ver [Arquitectura](docs/ARQUITECTURA.md#la-v2-investigación-y-captura-de-datos)).

## Funcionalidades

- **Universo dinámico:** las mayores criptomonedas por capitalización (CoinGecko) con perpetuo USDT en Bitunix, sin
  stablecoins ni tokens envueltos, refrescado cada 24 h.
- **Seis estrategias por reglas** (cruce de medias, tendencia con stop ATR, reversión RSI/Bollinger, ruptura de Donchian
  y dos variantes de funding contrario), con backtest propio sin sesgo de anticipación y criterios pre-registrados.
- **Simulador de operaciones:** comisiones, funding, deslizamiento, liquidación en margen aislado, mínimos del contrato,
  SL/TP/trailing evaluados con ticks en vivo y **reconciliación al reiniciar** con velas de 1 minuto. Aproxima la
  ejecución real; no la reproduce ([límites](docs/COSTOS_Y_LIMITES.md#de-la-simulación-frente-a-la-realidad)).
- **Motor de riesgo:** kill switch, stop por drawdown, *circuit breaker*, pérdida diaria, cupos por posición y dirección,
  tope de SL y bloqueo ante datos obsoletos. Solo bloquea entradas, nunca cierres.
- **Medición del valor del LLM:** sombras, etiquetas inmutables, prompt congelado con hash vigilado en cada ciclo, registro
  completo de cada llamada, presupuesto diario con corte duro, placebo y veredicto de tres estados.
- **Resultados ocultos por código** hasta el registro oficial del veredicto, en la API, el dashboard, Telegram y los informes.
- **Dashboard web** de seis pestañas (resumen, cuenta paper, brazo ejecutado, riesgo y controles, universo e
  indicadores) y **API** con sesión, de solo lectura salvo tres controles con confirmación.
- **Pestaña Indicadores (v2):** 14 indicadores como casillas combinables, temporalidades de 15m a 1 semana, salida en ATR
  o en porcentaje, % de operaciones ganadoras, profit factor y control al azar en segundos, sobre el historial local de
  Bitunix ([guía](docs/v2/SECCION_INDICADORES.md)). Es exploratoria: no cuenta como evidencia.
- **Investigación con preregistro (v2):** indicadores causales probados contra TradingView, candidatos y rondas
  exploratorias con selección solo en el periodo de entrenamiento y controles con dirección al azar
  ([especificación](docs/v2/ESPECIFICACION_INDICADORES.md)).
- **Captura de datos hacia adelante (v2):** libro de órdenes, funding y Fear & Greed en `history/market_v2.db`, con tareas
  programadas `MinervaV2*` que también mantienen al día el historial de velas.
- **Bot de Telegram:** comandos, avisos de posiciones y riesgo, resumen diario y alerta de caída.
- **Noticias gratuitas y memoria de lecciones** (apagadas durante la medición y fuera del prompt congelado).
- **Operación:** Docker (imagen sin privilegios, puerto solo en `127.0.0.1`), respaldos consistentes, mudanza de
  nativo a Docker con vuelta atrás y más de 2.800 pruebas automáticas de Python y más de 100 del frontend.

## Requisitos

| Para | Necesitas |
|---|---|
| Ejecutar el bot | **Docker** (Docker Desktop, o Docker Engine con Compose v2) y **Git** |
| Herramientas auxiliares (contraseña, respaldos, informes) | **Python 3.11 o 3.12** (no 3.13 ni superiores; en Windows con uv, usa el 3.11: [detalle](docs/GUIA_INSTALACION.md#antes-de-empezar)) |
| La IA (etiquetado) | Una cuenta de la **Claude Console** con facturación. Es lo **único que cuesta dinero**: del orden de 0,005 USD por señal, con tope diario (1 USD por defecto) |
| Avisos y comandos | Un bot de **Telegram** (gratis). Opcional |
| Compilar el dashboard sin Docker | **Node.js 22.22 o superior**. Opcional |

Todo lo demás (datos de mercado, universo, noticias) usa fuentes gratuitas sin tarjeta
([términos y atribuciones](docs/COSTOS_Y_LIMITES.md#fuentes-gratuitas-términos-y-atribuciones)). Desarrollado y probado en
Windows; la imagen de Docker es de Linux.

## Inicio rápido con Docker

```bash
git clone https://github.com/ProyectoJaviera/Minerva-v2.git
cd Minerva-v2
cp .env.example .env                          # Windows (PowerShell): Copy-Item .env.example .env
docker compose build                          # construye la imagen (~1 min la primera vez)
docker run --rm -it minerva-v2:local python scripts/hash_password.py    # imprime AUTH_PASSWORD_HASH='…'
```

1. **Edita el `.env`**: pega el hash que imprimió el último comando (con sus comillas simples), elige `AUTH_USERNAME`, pon
   un `JWT_SECRET` de al menos 32 caracteres y tu `ANTHROPIC_API_KEY`. Telegram y CoinGecko son opcionales. Paso a paso, con
   cómo conseguir cada credencial: [Guía de instalación](docs/GUIA_INSTALACION.md).
2. **Arranca** y comprueba que esté sano:

   ```bash
   docker compose up -d
   docker compose ps                          # STATUS pasa a "healthy" en ~1 minuto
   ```

3. Abre el dashboard en <http://127.0.0.1:8001/> (con el `AUTH_USERNAME` de tu `.env` y la contraseña que elegiste al
   generar el hash) y el estado en <http://127.0.0.1:8001/health>.

> En la v2 `MINERVA_REAL_BOT` vale `false` por defecto: el bot genera señales y sombras pero no llama a ninguna API de
> pago (ni a Telegram). Para encender el etiquetado con Claude, el brazo ejecutado, las noticias y los avisos, ponlo
> a propósito (`MINERVA_REAL_BOT=true`, con un `.env` **propio de la v2**). No verás resultados de la IA en ningún caso
> hasta el veredicto: **la medición es ciega** y toma meses.

## Documentación

Índice completo: [`docs/README.md`](docs/README.md).

| Documento | Para qué |
|---|---|
| [Guía de instalación](docs/GUIA_INSTALACION.md) | Instalar desde cero, conseguir cada credencial, primer arranque y verificación |
| [Configuración](docs/CONFIGURACION.md) | Todas las variables y los interruptores |
| [Uso diario](docs/USO.md) | Dashboard, Telegram, respaldos, reinicios seguros, actualizar y mudar |
| [Arquitectura](docs/ARQUITECTURA.md) | Componentes, flujo de datos, base de datos y decisiones de diseño |
| [Metodología](docs/METODOLOGIA.md) | Qué se mide, cómo y por qué los resultados están ocultos |
| [Solución de problemas](docs/SOLUCION_PROBLEMAS.md) | Preguntas frecuentes y errores comunes |
| [Seguridad](docs/SEGURIDAD.md) | Secretos, puertos, autenticación y cómo reportar un problema |
| [Costos y límites](docs/COSTOS_Y_LIMITES.md) | Costo medido, fuentes gratuitas y lo no verificado |
| [Glosario](docs/GLOSARIO.md) | Los términos del proyecto |
| [Pestaña Indicadores](docs/v2/SECCION_INDICADORES.md) | Probar combinaciones de indicadores a mano (v2) |
| [Investigación de la v2](docs/README.md#investigación-de-la-v2) | Preregistros, resultados de cada ronda y prueba hacia adelante |
| [Informe final de la v1](docs/INFORME_FINAL.md) | Qué se construyó en la v1, qué está verificado y qué no (fotografía del 2026-10-18) |
| [Historial de desarrollo](docs/historial/README.md) | Cómo se construyó, fase por fase, con ayuda de IA |

## Estructura del repositorio

```text
app/            Backend (FastAPI + asyncio): API, mercado, estrategias, riesgo, LLM, Telegram, persistencia
frontend/       Dashboard (React + Vite + Tailwind) con pruebas de Vitest
scripts/        Arranque y parada, respaldos, informes de la medición y del veredicto, mudanza a Docker
tests/          unit/, integration/, e2e/ y support/ (pruebas unitarias, de integración y de punta a punta)
docker/         Healthcheck, versiones exactas de dependencias y certificados opcionales
docs/           Documentación; docs/v2/ es la investigación de la v2 y docs/historial/ el registro del desarrollo
history/        Archivos locales de la v2 (historial de velas y datos capturados); fuera de git
.github/        Plantillas de issues y de pull requests
```

## Pruebas y contribuciones

```bash
pytest                               # unitarias, de integración y de punta a punta (~11 min)
ruff check .
npm --prefix frontend run test       # Vitest
npm --prefix frontend run build
```

Las pruebas no necesitan red ni credenciales (un candado bloquea cualquier conexión a un nombre que no sea local). Cómo
contribuir, las convenciones y la regla de no tocar el prompt congelado durante una medición:
[`CONTRIBUTING.md`](CONTRIBUTING.md). Cambios por fase: [`CHANGELOG.md`](CHANGELOG.md).

El proyecto se construyó con ayuda de un asistente de IA (Claude Code), fase por fase y con aprobación del autor en cada
una; las instrucciones que se le dieron están en [`CLAUDE.md`](CLAUDE.md).

## Licencia

[MIT](LICENSE).

---

## English summary

### About

**Minerva v2** is an experimental, paper-trading-only research bot. It inherits from v1 a blind measurement of one
question, *does an LLM filter improve the average result of rule-based technical trading signals?* (still running in
the v1 repository), and adds a pre-registered study of technical indicators, a dashboard tab to backtest any combination
of 14 indicators on local Bitunix history, and forward recording of order book, funding and Fear & Greed data. So far no
indicator strategy passed the pre-registered criteria. In v1, on every candle close it evaluates a dynamic universe of the largest crypto
perpetuals (Bitunix, ranked by CoinGecko) with six rule-based strategies. Each signal becomes a simulated *shadow trade*;
Claude (Anthropic) labels it `APROBADA` (approved) or `RECHAZADA` (rejected) with a **frozen** prompt; and a paper account
trades only the approved ones through a risk engine. The measurement is **blind**: no channel shows results until a single,
pre-registered analysis point (300 effective clusters per side) and an official verdict record exist. Status: the rule-based
strategies showed no demonstrable edge in backtest; the LLM measurement is running and the verdict is pending (months away);
no results are published. Documentation is in Spanish; code identifiers are in English.

### Quick start

```bash
git clone https://github.com/ProyectoJaviera/Minerva-v2.git && cd Minerva-v2
cp .env.example .env
docker compose build
docker run --rm -it minerva-v2:local python scripts/hash_password.py   # paste the printed line into .env
# edit .env: AUTH_USERNAME, AUTH_PASSWORD_HASH, JWT_SECRET (>= 32 chars), ANTHROPIC_API_KEY
docker compose up -d
```

Open <http://127.0.0.1:8001/> (dashboard) and <http://127.0.0.1:8001/health>. Requirements: Git, Docker with Compose v2,
Python 3.11/3.12 for helper scripts, and an Anthropic API key (the only paid component; about 0.005 USD per labeled
signal, with a hard daily cap). Full guide (in Spanish): [`docs/GUIA_INSTALACION.md`](docs/GUIA_INSTALACION.md).

### Disclaimer

**Paper trading only. Experimental. Not financial advice.** Minerva never sends real orders and has no exchange
credentials. Trading leveraged futures, real or simulated, can lose money, and nothing here guarantees profit. Simulated
results do not predict real-account results (latency, fees, slippage and exchange limits are only approximated). Provided
"as is" under the [MIT license](LICENSE), without warranty of any kind.
