# API reference

Handlers registered by `create_app` (`src/app.py:50-54`, `70-74`). Auth is optional bearer parsing (`src/auth/middleware.py:15-20`) unless the handler calls `require_user_id`. Error bodies for `/api/...` use `ProblemDetails` (`src/common/schemas/responses.py:13-24`) from `src/common/http/exception_handlers.py:26-56`.

Default rate limit, unless the handler declares its own: visitor 60 per 60 seconds, registered 300 per 60 seconds (`src/common/ratelimit/rules.py:20-21`). Exempt: `/docs`, `/redoc`, `/openapi.json`, `/health`, `/api/health` (`src/common/middleware/rate_limit.py:16`, `src/app.py:55-57`).

FastAPI still serves its default `GET /docs`, `GET /redoc`, and `GET /openapi.json` because `FastAPI(title="Propqa")` does not disable them (`src/app.py:41`).

## Registered routes

| Method | Path | Handler | Auth | Request | Response |
| --- | --- | --- | --- | --- | --- |
| GET | `/health` | `health` `src/app.py:70-72` | none | none | `{"status":"ok"}` |
| GET | `/api/health` | `api_health` `src/app.py:74-85` | none | none | `status`, `version` `0.1.0`, `flags.ws_mounted` false, `flags.hitl_transport` `sse`, `flags.cognitive_pipeline` false, `flags.ltm_enabled` true |
| POST | `/api/auth/register` | `register` `src/routes/auth.py:37-43` | none. Limit `auth.register` 5/3600s | `RegisterRequest` `src/routes/schemas/auth.py:29-36`: `name`, `email`, `password`, `phone` optional | 201 `AuthResponse` lines 121-126: `user`, `access_token`, `refresh_token`, `token_type` `bearer`, `expires_in` |
| POST | `/api/auth/login` | `login` `src/routes/auth.py:46-58` | none. Sign-in limits counted on failure | `LoginRequest` lines 76-80: `email`, `password` | 200 `AuthResponse` |
| POST | `/api/auth/refresh` | `refresh` `src/routes/auth.py:61-64` | none. `auth.token_refresh` 30/300s | `RefreshTokenRequest` lines 95-98: `refresh_token` | 200 `AuthResponse` |
| POST | `/api/auth/logout` | `logout` `src/routes/auth.py:67-70` | none. Token is the body. Default API ceiling | `RefreshTokenRequest` | 204 empty |
| GET | `/api/auth/me` | `me` `src/routes/auth.py:73-76` | `require_user_id` | none | `UserResponse` lines 109-114: `id`, `email`, `name`, `phone`, `role` |
| POST | `/api/chat` | `chat` `src/routes/chat.py:36-77` | none. `CHAT_VISITOR` 20/60s or `CHAT_REGISTERED` 60/60s | `ChatRequest` `src/routes/schemas/chat.py:11-24`: `message` 1-4000, `thread_id`, `session_id`, `user_id`, `session_profile`, `focused_property_ids` max 8 | `text/event-stream`. Headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `X-Thread-ID` |
| POST | `/api/sessions/new` | `new_session` `src/routes/sessions.py:34-37` | none | `NewSessionRequest` optional. Body is discarded (`sessions.py:36`) | `session_id`, `carried_over: []` |
| GET | `/api/sessions` | `list_sessions` `src/routes/sessions.py:40-42` | none | query `user_id` optional, `limit` default 30 | `{"sessions":[...]}` row keys from `SidebarSession.to_row` |
| GET | `/api/sessions/{session_id}/turns` | `session_turns` `src/routes/sessions.py:45-62` | none | path `session_id`, query `limit` default 30 | `session_id`, `turns`, `messages`, `knowledge: {}`, `summary: ""`. 404 or 503 |
| POST | `/api/sessions/forget_many` | `forget_many` `src/routes/sessions.py:65-68` | none | `ForgetSessionsRequest.session_ids` | `{"forgotten":[...]}` |
| POST | `/api/sessions/{session_id}/forget` | `forget_session` `src/routes/sessions.py:71-76` | none | path. Body discarded | `{"status":"forgotten"}` or 404 |
| POST | `/api/sessions/{session_id}/forget_all` | `forget_session_and_user_memory` `src/routes/sessions.py:79-85` | none. `user_id` from the body | `ForgetSessionsRequest.user_id` | `{"status":"forgotten"}` |
| POST | `/api/sessions/{session_id}/claim` | `claim_session` `src/routes/sessions.py:88-96` | `require_user_id` | `guest_user_id` | `{"status":"ok","claimed":bool}` |
| GET | `/api/sessions/{session_id}/quota` | `session_quota` `src/routes/sessions.py:99-102` | none | path, validated | `used` 0, `limit` 100, `remaining` 100, `exhausted` false |
| GET | `/api/sessions/{session_id}/context` | `session_context` `src/routes/sessions.py:105-108` | none | path, validated | `prompt_tokens` 0, `budget` 0, `fraction` 0, `compacted_turns` 0 |
| POST | `/api/sessions/{session_id}/context/compact` | `compact_session` `src/routes/sessions.py:111-113` | none | path. Does not call `_require_thread` itself | same object as context |
| GET | `/api/preferences` | `get_preferences` `src/routes/sessions.py:116-118` | none | query `user_id` | `{"preferences": dict or null}` |
| POST | `/api/preferences` | `save_preferences` `src/routes/sessions.py:121-124` | none | `SavePreferencesRequest` `src/routes/schemas/sessions.py:25-29`: `user_id`, `preferences` | `{"preferences": merged}` |
| DELETE | `/api/preferences` | `delete_preferences` `src/routes/sessions.py:127-131` | none | query `user_id`. `session_id` ignored | `{"status":"deleted"}` |
| GET | `/api/leads/property-contact` | `property_contact` `src/routes/leads.py:16-26` | none | query `property_id` integer `gt=0` | `{"contact":{...}}` or `ResourceNotFound` or `DatabaseFailure` |
| GET | `/api/users/{user_id}/memory` | `export_memory` `src/agent/memory/routes/user_memory.py:12-14` | none | path `user_id` | list of `id`, `content`, `provenance`, `confidence`, `created_at`, `type`, `cluster` (`src/agent/memory/maintenance/privacy.py:67-76`). 503 if the store is missing |
| DELETE | `/api/users/{user_id}/memory` | `delete_memory` `src/agent/memory/routes/user_memory.py:17-23` | none | query `cluster` or `memory_id` | `{"status":"deleted","count":n}`. 400 if neither query is set or `cluster` is unknown |

`UserResponse.role` is the `UserRole` stored on the user. The check constraint allows `user` and `admin` (`src/auth/storage/postgres.py:22`).

### `POST /api/chat` events

Framing is `event: {name}\ndata: {json}\n\n` (`src/routes/chat.py:80-82`). The first chunk is `: ok\n\n` (line 50).

| Event | Payload added for the client | Produced by |
| --- | --- | --- |
| `text` | `delta`, and `token` copied from `delta` when `token` is absent (`chat.py:89-90`) | reply streaming, interrupt prompt (`src/agent/graph/runner.py:113`) |
| `listings` | `ids`, `cards` | `src/agent/graph/nodes/lookup.py:116` |
| `reply` | structured reply object | `src/agent/reply/streaming.py` via `publish_structured_reply` |
| `done` | `thread_id`, `route`, `paused`, plus `done: true` (`chat.py:91-92`) | `src/agent/graph/runner.py:117-122` |
| `error` | `detail`, and `error` copied from `detail` (`chat.py:93-94`) | `src/routes/chat.py:67` |

### Contact object

Keys from `contact_sheet_from_row` (`src/agent/sql/contact.py:55-82`): `property_id`, `agent_id`, `agent_name`, `company_name`, `phone`, `mobile`, `whatsapp`, `email`, `verification_status`, `contact_source`. `contact_source` is `agency` or `listing_agent`.

## Frontend calls with no registered handler

These `fetch` paths exist in `Frontend_Gerenal` and do not appear on a router included by `create_app`.

| Method | Path | Caller |
| --- | --- | --- |
| POST | `/api/chat/resume` | `Frontend_Gerenal/src/api/sseClient.ts:155` |
| POST | `/api/chat/{runId}/cancel` | `Frontend_Gerenal/src/api/sseClient.ts:176` |
| GET | `/api/flows` | `Frontend_Gerenal/src/store/chatStore.ts:46` |
| POST | `/api/leads/submit` | `Frontend_Gerenal/src/hooks/useChat.ts:1284` |
| POST | `/api/leads/agents` | `Frontend_Gerenal/src/hooks/useChat.ts:1332` |
| POST | `/api/leads/agents/dismiss` | `Frontend_Gerenal/src/hooks/useChat.ts:1377` |
| POST | `/api/leads/cta-click` | `Frontend_Gerenal/src/hooks/usePropertyContact.ts:105` |
| POST | `/api/realtime/voice-session` | `Frontend_Gerenal/src/api/voiceSessionApi.ts:41` |
| GET | `/api/analytics/funnels` | `Frontend_Gerenal/src/api/analyticsApi.ts:113` |
| GET | `/api/analytics/engagement` | `analyticsApi.ts:130` |
| POST | `/api/feedback/thumbs` | `analyticsApi.ts:152` |
| POST | `/api/feedback/correction` | `analyticsApi.ts:179` |
| GET | `/api/feedback/stats` | `analyticsApi.ts:200` |
| GET | `/api/admin/eval-runs` | `analyticsApi.ts:211` |
| GET | `/api/admin/prompt-versions` | `analyticsApi.ts:223-224` |
| GET | WebSocket `/ws/chat` | `Frontend_Gerenal/vite.config.ts:40`, `Frontend_Gerenal/nginx.conf:25` |

`Frontend_Gerenal/src/lib/voiceRealtime.ts` also posts to `https://api.openai.com/v1/realtime/translations/calls`. That host is not this API.

A missing route becomes the API 404 Problem Details path for paths under `/api/` (`src/common/http/exception_handlers.py:87-89`).
