# Minerva v2: bot de trading autónomo (PAPER TRADING)

## Qué es este repositorio
- Esta es la **versión 2** de Minerva. Parte de la **etiqueta `v1.0`** del repositorio **Minerva-v1** (el mismo código y el mismo historial de git); desde ahí sigue su propio camino.
- La **medición ciega de la v1 sigue su curso en otro repositorio** (Minerva-v1), con su propio bot vivo en Docker. Esta v2 **no la toca ni la reemplaza**: la v1 está congelada y su resultado se registra allí.
- Todo desarrollo nuevo (incluidos los indicadores de TradingView) se hace **aquí**. Los cambios de la v1 se limitan a documentación, correcciones fuera de las zonas protegidas y el registro oficial del veredicto, y se hacen en el repositorio de la v1.

## Contexto
Especificación de la v1 en docs/historial/SPEC.md y base previa en docs/historial/openspec.md (nunca probada: evalúala críticamente, no la copies a ciegas). El índice de la documentación vigente está en docs/README.md; la técnica, en docs/dev/. Esa documentación se heredó de la v1 y todavía habla en sus términos: donde difiera del README o de este archivo, manda el código y la nota de la v2 del README.

## Idioma
Todas las respuestas, resúmenes y documentos para este proyecto deben estar en español. Los identificadores de código (variables, funciones, clases, tablas, columnas) siguen en inglés.

## Reglas críticas
- La v2 es 100% paper trading. Prohibido escribir código que envíe órdenes reales a Bitunix. La ejecución real solo existe como interfaz/documentación (BitunixBackend desactivado).
- Nunca leas, imprimas ni pidas archivos .env ni credenciales. Usa solo .env.example con valores vacíos. Nunca incluyas claves en código, tests, logs ni commits.
- **Jamás copies el `.env` real de la v1 a la v2** (ni sus claves, su token de Telegram o su clave de Anthropic): la v2 tiene su propio `.env`, que crea y llena su dueño a mano.
- No inventes endpoints, parámetros ni firmas de Bitunix/CoinGecko. Verifica con la documentación oficial o los ejemplos del repo oficial antes de implementar; si no puedes verificar, dilo.

## Aislamiento de la v1 (el bot vivo de la v1 corre en este mismo PC)
- Los nombres de la v2 son otros a propósito: proyecto y contenedor `minerva-v2`, imagen `minerva-v2:local`, volúmenes `minerva-v2_data` y `minerva-v2_logs`, puerto `8001`, tareas programadas con prefijo `MinervaV2` y marca `MIGRADO_A_DOCKER_V2.txt`. Los scripts rechazan los nombres de la v1 (proyecto `minerva`, puerto 8000, tareas `MinervaStartBot`, `MinervaHealthAlert`, `MinervaDailySummary`, `MinervaBackup`). No los debilites ni los esquives.
- `MINERVA_REAL_BOT` vale `false` por defecto: la v2 arranca sin etiquetado del LLM, Telegram, brazo ejecutado, noticias ni push. Encenderlos es una decisión explícita de su dueño, con un `.env` propio de la v2.
- Todo desarrollo y prueba usa una **DB temporal** y el **puerto 8001** (el servidor de desarrollo y el contenedor de la v2 comparten ese puerto por defecto: no corras los dos a la vez). Nunca apuntes nada de la v2 a la base ni a los volúmenes de la v1.

## Flujo de trabajo
- Antes de un cambio grande: investiga y propón un plan. Para los pequeños, decide con criterio y sigue.
- Haz commits pequeños con mensajes claros (Conventional Commits).
- Pruebas: pytest + pytest-asyncio. Toda función de riesgo y de simulación (SL/TP/trailing, liquidación, comisiones, funding) debe tener tests con casos límite.
- Antes de dar por terminada cualquier tarea que toque el pipeline de datos o la persistencia, ejecuta un smoke test de punta a punta con un subconjunto pequeño; que los tests unitarios pasen no es suficiente.
- Todo script que lea una base real debe ejecutarse antes de entregarlo contra una copia temporal de esa base (ruta distinta de `settings.database_path`, verificada con un assert explícito); los tests con datos sintéticos no bastan para esto.
- **En la v2 el prompt congelado y las zonas protegidas de la v1 se pueden cambiar** (`docs/dev/ZONAS_PROTEGIDAS.md` describe la v1). Pero **cualquier cambio de comportamiento respecto de la v1.0** (prompt, estrategias, niveles SL/TP, riesgo, esquema de la base, configuración por defecto) **debe quedar anotado en docs/historial/PROGRESS.md**, con el motivo, para saber qué resultados dejan de ser comparables con los de la v1.
- Mantén docs/historial/PROGRESS.md: decisiones, cambios de comportamiento y pendientes.

## Autonomía
- Trabaja de corrido hasta terminar la tarea completa. No pidas confirmación ni hagas preguntas intermedias: decide con criterio, anota la decisión en docs/historial/PROGRESS.md y sigue. Solo te detienes al terminar, o si algo exige una decisión irreversible del dueño del proyecto.
- Los scripts de prueba temporales van en el directorio scratchpad y se reutilizan; no crees un archivo de prueba nuevo por intento.
- Límites absolutos aunque ningún permiso los frene: nunca detener, matar, reiniciar ni reconstruir el bot vivo de la v1 (puerto 8000, proyecto `minerva`, contenedor `minerva-minerva-1`, imagen `minerva:local`); nunca tocar su base, sus volúmenes ni sus tareas programadas; nunca modificar, mover ni borrar archivos en `data/` de ninguno de los dos repositorios; nunca leer ni imprimir `.env`.
- Push: al terminar cada tarea, con pytest y ruff en verde, haz `git push origin master` **de este repositorio (Minerva-v2)**; nunca `--force`, nunca otra rama, y nunca subas `.env`, `data/` ni `logs/`.

## Stack y convenciones
- Python 3.11+, asyncio, FastAPI, SQLite (aiosqlite). Tipado con type hints; formateo con ruff.
- Toda decisión del LLM se valida con esquema (pydantic) y se registra completa en la base de datos.
- El bot corre en Docker Compose en el PC de su dueño, no dentro de Claude Code. Puedes levantarlo para probar solo si el dueño lo pide, siempre en modo paper y con el proyecto `minerva-v2`.

## Comandos
- Tests: pytest
- Lint: ruff check .
- Levantar (lo hace su dueño): docker compose up --build

## Restricción de costos (obligatoria)
- Lo único que puede costar dinero es la API de Claude (Anthropic), con presupuesto diario y corte duro configurables.
- Todo lo demás debe ser gratuito y sin tarjeta de crédito: APIs, librerías, datos, hosting (PC local) y herramientas.
- Antes de integrar cualquier servicio externo, verifica en su documentación oficial: plan gratuito real, límites de uso, términos (uso no comercial, atribución) y si pide tarjeta. Si no cumple, propón una alternativa gratuita o descártalo.
- Diseña para fuentes gratuitas poco fiables: caché local, reintentos con backoff, degradación controlada, registro de salud por fuente y bloqueo de nuevas operaciones si los datos críticos están obsoletos.
- Respeta límites de uso y atribuciones (p. ej. "Data provided by CoinGecko" visible en el frontend).

## Formato de comandos (para evitar solicitudes de permiso)
- El directorio de trabajo ya es la raíz del proyecto: NO uses `cd`.
- Un solo comando por llamada. No encadenes con `&&`, `;` ni `&`.
- Para cambiar de carpeta dentro de un comando usa las opciones propias de la herramienta (p. ej. `npm --prefix frontend run build`, `git -C ...`), no `cd`.
- Mensajes de commit de una sola línea con `git commit -m "tipo: descripción"`, sin saltos de línea ni trailers.
- No redirijas salidas a archivos temporales (`> build.log`, `> out.txt`) ni borres archivos después; lee la salida directamente.
