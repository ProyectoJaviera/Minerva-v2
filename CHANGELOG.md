# Registro de cambios

Resumen **por fases** de cómo se construyó Minerva (lo más reciente primero). Minerva todavía no tiene versiones
numeradas ni etiquetas: el repositorio se llevó por fases, y cada una cerró con las pruebas en verde y la aprobación
de su autor. El detalle commit por commit está en `git log`, y la bitácora completa del desarrollo en
[`docs/historial/`](docs/historial/README.md) (con [`docs/INFORME_FINAL.md`](docs/INFORME_FINAL.md) como resumen).

Las fechas son las de los commits (2026). **Nada de lo que hay aquí envía órdenes reales**: todo es paper trading.

## Minerva v2: captura de datos y documentación — 2026-11-11

- `scripts/record_market_data.py` graba hacia adelante el libro de órdenes de Bitunix (50 niveles), el funding vigente y
  el Fear & Greed en `history/market_v2.db`; `scripts/register_v2_data_tasks.ps1` registra las tareas
  `MinervaV2OrderBook`, `MinervaV2Funding`, `MinervaV2FearGreed` y `MinervaV2HistoryUpdate`.
- `scripts/update_history_file.py --via-copy` actualiza el historial en una copia y la cambia al final.
- Documentación actualizada a la v2: README, índice, arquitectura, guía de instalación, glosario y avisos en los
  documentos que solo describen la medición de la v1.

## Minerva v2: pestaña Indicadores — 2026-11-10 y 2026-11-11

- Pestaña **Indicadores** del dashboard (exploratoria): 14 indicadores como casillas combinables por confluencia
  («todos» o «al menos N»), temporalidades 15m, 1h, 4h, 1D y 1S, salida en ATR o en porcentaje y control con dirección
  al azar, sobre el archivo de historial local `history/history_v2.db` (solo lectura). API `GET /api/explorer/options` y
  `GET /api/explorer/run`.

## Minerva v2: investigación de indicadores — 2026-11-08 a 2026-11-11

- Indicadores causales reimplementados (SFP y zonas de liquidez del HeatMap, Range Filter, VIDYA, Camarilla, BB%B,
  WaveTrend), comparados con TradingView.
- Preregistro congelado y corrida única de la Fase 2: los tres candidatos descartados. Exploración de 176 combinaciones,
  rondas 3 y 4: nada pasa los criterios; los finalistas de la ronda 3 perdieron en los datos reservados.
- Prueba hacia adelante de los finalistas y de la fuerza relativa semanal (`scripts/v2_forward_test.py`).
- Motor de backtest: omitir la entrada si el `open` ya cruzó el SL, entrada con orden límite y salida por tiempo
  (opcionales; las operaciones de las estrategias de la v1 no cambian).

## Minerva v2: inicio y aislamiento de la v1 — 2026-11-05

- La v2 parte de la etiqueta `v1.0` del repositorio Minerva-v1 (mismo código e historial); la medición ciega de la v1
  sigue su curso en ese otro repositorio.
- Nombres propios para que ningún comando de la v2 pueda tocar el bot vivo de la v1: proyecto y contenedor `minerva-v2`,
  imagen `minerva-v2:local`, volúmenes `minerva-v2_data` y `minerva-v2_logs` y red `minerva-v2_default` (fijados por
  nombre en el compose), puerto del equipo `8001`, tareas programadas `MinervaV2…` y marca `MIGRADO_A_DOCKER_V2.txt`.
- `MINERVA_REAL_BOT` vale `false` por defecto: sin etiquetado del LLM, Telegram, brazo ejecutado, noticias ni avisos.
- Candados: `start_bot.ps1`, `stop_bot.ps1`, `migrate_to_docker.ps1` y `rollback_from_docker.ps1` rechazan el puerto 8000;
  los de la mudanza rechazan además el proyecto `minerva` y las tareas de la v1; `scripts/docker_support.py` rechaza el
  proyecto `minerva` y pasa siempre `-p`. Pruebas nuevas en `tests/unit/test_v1_isolation.py`.
- `CLAUDE.md` reescrito para la v2 (sin las reglas de congelamiento de la v1; todo cambio de comportamiento respecto de
  la v1.0 se anota en `docs/historial/PROGRESS.md`).
- Sin cambios de comportamiento de `app/` respecto de la v1.0.

## Variante de la imagen para procesadores sin SSE4 — 2026-10-26

- Nuevo `docker/requirements.old-cpu.lock`: las mismas versiones exactas que `docker/requirements.lock` salvo
  `numpy==2.3.5`, para equipos como un Intel Atom N570 (solo hasta SSSE3), donde NumPy 2.4 muere con «Instrucción
  ilegal». Lo genera `scripts/export_docker_requirements.py` (con `--check` para ambos archivos).
- El `Dockerfile` acepta `ARG REQUIREMENTS_FILE` (por defecto `docker/requirements.lock`): la construcción normal no
  cambia. Para la variante: `--build-arg REQUIREMENTS_FILE=docker/requirements.old-cpu.lock`. Ver
  [`docs/GUIA_INSTALACION.md`](docs/GUIA_INSTALACION.md#procesador-antiguo-sin-sse4).
- Comprobado: indicadores, señales y niveles SL/TP calculados sobre una copia de la base real con NumPy 2.4.6 y con
  2.3.5 son idénticos bit a bit; la imagen de la variante corre sobre una CPU emulada sin SSE4 y la normal no.
- Sin cambios en `app/`, en el prompt congelado ni en la medición.

## Documentación técnica para desarrolladores — 2026-10-24

- Nueva carpeta [`docs/dev/`](docs/dev/README.md) para quien modifica el código: las
  [zonas protegidas de la medición](docs/dev/ZONAS_PROTEGIDAS.md) (qué no se puede cambiar y por qué), el flujo de
  ejecución, el modelo de datos, el entorno de desarrollo, las pruebas y las recetas de los cambios comunes, y una
  guía por paquete con cada archivo.
- Referencia automática de `app/` y `scripts/` generada con pdoc (`docs/dev/api/`, regenerada con
  `scripts/build_dev_docs.py`); docstrings completos en todo el código público (`Args`, `Returns`, `Raises` y
  `Efectos:`), exigidos por una prueba.
- `scripts/check_measurement_safety.py`: compara los cambios con la lista de zonas protegidas y avisa qué archivos,
  parámetros o tablas protegidos se tocaron (solo lee; gancho pre-commit opcional, no instalado).
- Pruebas que vigilan que esta documentación esté completa, al día y coincida con el código.
- Sin cambios de comportamiento en `app/`, en el prompt congelado ni en la medición: solo docstrings y comentarios.

## Documentación pública — 2026-10-23

- Nueva documentación para quien llega sin contexto: [`README.md`](README.md), [`docs/README.md`](docs/README.md)
  (índice), guía de instalación, configuración (todas las variables), arquitectura, metodología, uso diario,
  solución de problemas, glosario, seguridad y costos y límites.
- Los planes por fase, `PROGRESS.md` y los documentos internos pasaron a [`docs/historial/`](docs/historial/README.md).
- Licencia MIT, guía de contribución, plantillas de *issue* y de *pull request*.
- Pruebas que vigilan la documentación: enlaces y anclas, variables de `.env.example`, scripts y opciones citados,
  rutas de la API, comandos de Telegram y ausencia de rutas o nombres personales.
- Sin cambios en `app/`, en el prompt congelado ni en la medición.

## Fase 7 — Mudanza del bot a Docker y limpieza de consolas — 2026-10-18 a 2026-10-22

- Probado contra Docker real: 5 defectos corregidos que las pruebas estáticas no veían (respaldos en modo WAL de solo
  lectura, hash de contraseña mutilado por `env_file`, código de la imagen escribible, carpeta `.env` creada por Docker
  Desktop y arranque con Windows).
- `scripts/migrate_to_docker.ps1` (con `-DryRun`, ventana segura y vuelta atrás automática) y
  `scripts/rollback_from_docker.ps1`; `scripts/docker_db.py` (respaldo, copia y informes sobre una copia fresca),
  `scripts/db_fingerprint.py` y la marca `data/MIGRADO_A_DOCKER.txt` que protege la base nativa vieja.
- `scripts/hash_password.py` imprime el hash entre comillas simples (Compose interpolaba los `$`).
- Las pruebas y los scripts ya no abren ventanas de consola en Windows y ninguna prueba puede tocar el Programador de
  tareas real (trampa y guardianes).

## Fase 6 — Docker, pruebas de punta a punta, documentación y limpieza — 2026-10-18

- Imagen Docker multietapa (usuario sin privilegios, versiones exactas de dependencias, puerto solo en `127.0.0.1`),
  `docker-compose.yml`, healthcheck.
- 51 pruebas de punta a punta con el sistema real y solo el exterior simulado (incluido un barrido de que, con la
  puerta de resultados cerrada, ningún canal muestra resultados).
- Herramientas de operación: `backup_db.py`, `restore_db.py`, `resume_drawdown_stop.py`, `measurement_identity.py`,
  `export_schema_doc.py` (genera [`docs/ESQUEMA_BD.md`](docs/ESQUEMA_BD.md)).
- Limpieza: 7 campos de configuración sin uso retirados, `.env.example` completo, escaneo de secretos de lo versionado.

## Fase 5 — Dashboard, controles y notificaciones — 2026-10-14 a 2026-10-18

- Autenticación de un solo usuario (bcrypt, sesión en cookie `httpOnly`), API de solo lectura con listas blancas.
- Dashboard de cinco pestañas (*Resumen*, *Cuenta paper*, *Brazo ejecutado*, *Riesgo y controles*, *Universo y
  backtest*); controles de pausar, reanudar y kill switch con confirmación, mismo origen y auditoría.
- Notificaciones push por Telegram en una tarea aislada que solo lee la base.

## Fase 4 — Noticias y memoria de lecciones — 2026-10-17

- Recolección de noticias gratuita y determinista (GDELT, comunicados de la Fed, Fear & Greed), con atribución y salud
  por fuente. Memoria de lecciones y *post-mortem*. Ambas **apagadas** durante la medición y fuera del prompt congelado.
- Prompt v5 y *features* v3 preparados y **sin usar**.

## Fase 3 — Riesgo, simulación, señales, sombras, medición del LLM y brazo ejecutado — 2026-10-02 a 2026-10-17

- 3.1 y 3.2 (10-02): lógica de SL/TP/trailing compartida con el backtest y motor de riesgo en vivo.
- 3.3 a 3.5 (10-03 y 10-04): generador de señales, monitor de posiciones con reconciliación al reiniciar, operaciones
  sombra y análisis por conglomerados.
- 3.6 (10-04 a 10-17): decisión del LLM, `llm_logs`, etiqueta inmutable, presupuesto con corte duro, pilotos v1 a v4,
  **congelamiento del prompt** (10-12), etiquetado en vivo, regla de tres veredictos, placebo y herramientas del
  veredicto.
- Estabilidad (10-10 y 10-11): detección y reparación de huecos en las velas de 1 minuto que usa la reconciliación,
  *logging* no bloqueante, latido y `GET /health`.
- 3.7 (10-17): bot de Telegram por *long-polling* con confirmación de dos pasos.
- 3.8 y 3.9 (10-17): reporte de paso a dinero real (solo recomienda) y brazo ejecutado de la cuenta paper.
- Resultados ocultos hasta el registro oficial del veredicto (regla del 2026-10-17).

## Fase 2 — Universo dinámico y backtest — 2026-09-30 a 2026-10-04

- Universo (CoinGecko ∩ perpetuos USDT de Bitunix), seis estrategias por reglas y un motor de backtest sin sesgo de
  anticipación, con criterios de descarte escritos antes de correr.
- Resultado: **ninguna estrategia por reglas supera los criterios** (reejecución v2 vigente).

## Fase 1 — Estructura y datos de mercado — 2026-09-30

- Cliente REST y WebSocket públicos de Bitunix, caché de velas, indicadores, `PaperBackend`, persistencia con SQLite,
  scheduler, API y frontend mínimos.

## Fase 0 — Evaluación y diseño — 2026-09-30

- Evaluación crítica de un diseño previo (`openspec.md`, nunca probado), verificación de las APIs contra su
  documentación oficial y decisiones de diseño.
