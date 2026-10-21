# Runbook

Commands below are the ones in [README.md](../README.md) and [compose.yaml](../compose.yaml). Variable meanings are in [WORKFLOW.md](WORKFLOW.md) section 8. Do not commit filled env files. `README.md:60` says `.env` and `{APP_ENV}.env` are gitignored. `example.env` is the template.

## Local process layout

Day-to-day setup runs Postgres and Redis in Docker and the API, worker, and Vite app on the host (`README.md:84-85`).

### 1. Postgres and Redis

```powershell
docker compose up -d postgres redis
```

Host ports from `compose.yaml:81` and `98`: Postgres `127.0.0.1:5434`, Redis `127.0.0.1:6381`, unless `POSTGRES_PORT` or `REDIS_PORT` is set. The database name and role inside the container are `propqa_chatbot` and `propqa` (`compose.yaml:76-78`). Password is `${POSTGRES_PASSWORD:-propqa}`.

`README.md:102-111` tells a host-run API to set:

```text
CHAT_DB_HOST=127.0.0.1
CHAT_DB_PORT=5434
CHAT_DB_NAME=propqa_chatbot
CHAT_DB_USER=propqa
CHAT_DB_PASSWORD=<same as POSTGRES_PASSWORD>
CHAT_DB_SSLMODE=disable
REDIS_URL=redis://127.0.0.1:6381/0
```

`example.env` points at port 5432 and `redis://localhost:6379/0` (`README.md:102`). Those match the code defaults (`src/config/settings.py:70`, `82`), not the Compose host ports.

Warehouse answers need `AUDIT_DB_*` (`README.md:49`). Chat that never takes the `need_db` path can run without them. The first warehouse call opens the pool (`src/agent/sql/execute.py:61-67`).

### 2. Environment file

```powershell
copy example.env development.env
Set-Content -Path .env -Value "APP_ENV=development"
```

That sequence is `README.md:62-65`. `src/config/settings.py:14-16` loads `.env` then `{APP_ENV}.env`.

`JWT_SIGNING_KEY` may be empty in development. The process logs a warning and uses a random key (`src/auth/tokens.py:42-45`). Staging and production refuse to start without a key of at least 32 bytes (`tokens.py:37-41`).

Set `LLM_PROVIDER` to `anthropic` or `openai` and the matching API key (`README.md:48`). `DOMAIN_ROUTER=llm` skips Jev (`README.md:51`).

### 3. API

```powershell
uv sync
$env:PYTHONPATH = "src"
uv run python src/app.py
```

Listens on `APP_HOST`:`APP_PORT`, default `0.0.0.0:8000` (`src/config/settings.py:42-43`, `src/app.py:100-104`). Check `http://127.0.0.1:8000/health`.

### 4. Memory worker

```powershell
$env:PYTHONPATH = "src"
uv run python -m agent.memory.worker
```

Skip this and chat still streams. Extracted jobs stay on `memq` (`compose.yaml:60-61`).

### 5. UI

```powershell
cd Frontend_Gerenal
npm ci
npm run dev
```

Open `http://localhost:5173`. The dev server proxies `/api` to `127.0.0.1:8000` (`Frontend_Gerenal/vite.config.ts:32-38`). Start the API first (`README.md:139`).

## Full stack in Docker

```powershell
docker compose up -d --build
```

Compose reads `${APP_ENV:-production}.env` (`compose.yaml:11`) and then overrides `CHAT_DB_*` and `REDIS_URL` to the service names (`compose.yaml:14-20`).

| Surface | URL |
| --- | --- |
| UI | `http://localhost:8080` (`WEB_PORT` default 8080, `compose.yaml:54`) |
| API on the host | `http://127.0.0.1:8010` (`API_PORT` default 8010, `compose.yaml:41`) |

One-shot consolidation:

```powershell
docker compose --profile jobs run --rm consolidate
```

`consolidate` is not started by `up` (`compose.yaml:66-71`).

## Tests

Backend (`README.md:174-177`, `pyproject.toml:34-36`):

```powershell
uv sync --extra dev
uv run pytest
```

Frontend, from `Frontend_Gerenal` (`package.json:10-14`):

```powershell
npm run test
npm run test:e2e
npm run lint
```

There is no CI workflow in the repository.

## Evals and profiler

From the repo root, with `PYTHONPATH=src`:

| Command | Output |
| --- | --- |
| `python -m evals.run_domain_eval` | Prints domain-router results. Arguments are in `src/evals/run_domain_eval.py` |
| `python -m evals.run_sql_eval` | Writes `logs/sql_eval_<timestamp>.json` (`src/evals/run_sql_eval.py:66`) |
| `python -m catalog.profiler` | Writes YAML under `src/catalog/profiles/` (`src/catalog/profiler.py:10`) |

## Schema

No Alembic directory and no migration command. `PostgresUserRepository.ensure_schema` runs the auth DDL (`src/auth/storage/postgres.py:50-53`). `open_long_term_store` runs the memory DDL and raises if `CREATE EXTENSION vector` fails (`src/agent/memory/session/backends.py:59-66`).

## Troubleshooting

| Symptom | Where to look |
| --- | --- |
| Process exits before listen, deployed | `JWT_SIGNING_KEY` (`src/auth/tokens.py:40-41`) |
| `REDIS_URL is required for chat checkpoints` | Empty `REDIS_URL` outside tests (`src/agent/checkpointer/saver.py:60-61`). `TestConfig` blanks it on purpose (`src/config/settings.py:142`) |
| `Memory schema needs Postgres with pgvector` | Chat database image is not pgvector, or the role cannot create extensions (`src/agent/memory/session/backends.py:64-66`) |
| First chat turn is slow | Grounding wait, up to 30 seconds (`src/agent/graph/nodes/lookup.py:33-47`). Log `grounding.load_failed` |
| SSE `error` `I couldn't complete that reply.` | `chat stream failed` in the log (`src/routes/chat.py:65-67`) |
| Reply says it could not work that out | Warehouse or SQL guard failed and the prose fallback was empty (`src/agent/graph/nodes/reply.py:236-262`) |
| Sidebar chats never become memories | Worker process is not running (`compose.yaml:60-61`) |
| `GET /api/sessions/{id}/turns` returns 503 | Checkpoint read raised (`src/routes/sessions.py:50-52`) |
| Browser calls fail from an origin other than localhost:5173 | CORS list (`src/app.py:23-26`). The Docker UI is same-origin on port 8080 |
| UI action returns 404 | The path may be one of the unregistered frontend calls in [API_REFERENCE.md](API_REFERENCE.md) |
| Tokens invalid after an API restart in development | Ephemeral JWT key (`src/auth/tokens.py:31-32`) |
| `DEBUG=true` in `production.env` still hides exception text | `ProductionConfig.DEBUG = False` (`src/config/settings.py:145-146`) |

Logs: JSON on stderr. A rotating file `logs/app.log` when `LOG_TO_FILE` is true (`src/common/logger/setup.py:31-39`). Compose sets `LOG_TO_FILE` false (`compose.yaml:22`). Per-node durations are `node.timing` (`src/agent/graph/workflow.py:128-131`).

Health: `GET /health` is the Compose check (`compose.yaml:43`). `GET /api/health` does not probe Redis, Postgres, or the model (`src/app.py:74-85`).
