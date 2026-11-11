# Propqa chatbot API

This backend is a separate service. The UI on the other domain calls it with `fetch`. Base URL:

```text
https://<api-host>
```

Every path below is under that host. Example: `POST https://<api-host>/api/chat`.

The demo UI in this repo is not the product. Do not copy its extra routes. Only the routes in this file are implemented.

## Before the browser can call a different domain

CORS currently allows only `http://localhost:5173` and `http://127.0.0.1:5173`. A page on any other origin receives `400 Disallowed CORS origin` and the browser hides the response. The API host must add the frontend origin before integration from that domain works. There is no request the frontend can send to turn CORS on.

Until that origin is allowed, test with curl or with a page served from `http://localhost:5173`.

## How to call

Send `Content-Type: application/json` on every body. Send `Accept: application/json` except for chat, which returns a stream.

**Guest.** Generate one id and keep it in local storage. Send that same value as `user_id` on every guest call that accepts it. That id is what groups the sidebar, preferences, and memory.

```text
anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f
```

The part after `anon-` must be a UUID.

Do not send that value as `X-Visitor-ID`. The server keeps that header only when the whole value is a UUID or letters and numbers, at most 64 characters. `anon-<uuid>` is ignored. If the header is missing or ignored, the server mints a new visitor id, sets the cookie below, and returns that minted id on the response header `X-Visitor-ID`. Do not store the minted id. Chats are saved under the `user_id` in the body.

The server also sets an `HttpOnly` cookie for a guest. JavaScript cannot read it. Do not rely on the cookie. When the API runs as production or staging, that cookie is `Secure` and is not stored on plain HTTP.

**Signed in.** Send the access token:

```text
Authorization: Bearer <access_token>
```

On chat, sessions, preferences, memory, and forget, also send `user_id` equal to `user.id` from register, login, or `GET /api/auth/me`.

The server does not compare `user_id` to the token or to `X-Visitor-ID`, and a different value is not **403**. It stores the chat under the `user_id` you send. On chat, an invalid `user_id` is ignored and the caller id is used instead: the account id when a token is present, otherwise the minted visitor id. On preferences, an invalid `user_id` is **422** with `detail` “user_id is invalid.”

**Chat is not EventSource.** `EventSource` cannot `POST` and cannot set these headers. Use `fetch`, then read `response.body` as a stream of `text/event-stream`.

**Errors** are `application/problem+json`:

```json
{
  "type": "https://<api-host>/errors/bad_data",
  "title": "Validation failed",
  "status": 422,
  "detail": "message: Message is empty.",
  "instance": "/api/chat",
  "code": "VALIDATION",
  "subcode": "BAD_DATA",
  "trace_id": "bf1704182cbe4fd79128a94a3dc874a1",
  "errors": [{ "field": "message", "problem": "Message is empty." }]
}
```

Use `status`, `detail`, and `code`. Ignore `type` if it still points at an old host. A missing session returns **404** with `detail` “This endpoint does not exist.” Treat 404 on `/api/sessions/...` as “session not found.”

Access tokens last **900 seconds** (`expires_in`). Call refresh before they expire. Logout revokes the refresh token only. The access token keeps working until it expires.

## Health

### `GET /health`

No auth.

```json
{ "status": "ok" }
```

### `GET /api/health`

No auth.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "flags": {
    "ws_mounted": false,
    "hitl_transport": "sse",
    "cognitive_pipeline": false,
    "ltm_enabled": true
  }
}
```

`ws_mounted: false` means there is no WebSocket. Chat is the SSE route below.

## Auth

### `POST /api/auth/register`

No auth header. **201**

```json
{
  "name": "Sara Ali",
  "email": "sara@example.com",
  "password": "Secret12",
  "phone": "+971500000000"
}
```

`name` is 2–100 characters. `password` is at least 8 characters and must contain one uppercase letter and one number. `phone` is optional, max 20 characters.

```json
{
  "user": {
    "id": "da89e70a-87a5-4886-9ec5-0d64e9823ffb",
    "email": "sara@example.com",
    "name": "Sara Ali",
    "phone": "+971500000000",
    "role": "user"
  },
  "access_token": "<access_token>",
  "refresh_token": "<refresh_token>",
  "token_type": "bearer",
  "expires_in": 900
}
```

Duplicate email is **409**.

### `POST /api/auth/login`

```json
{ "email": "sara@example.com", "password": "Secret12" }
```

**200** with the same body as register. Wrong password is **401**:

```json
{
  "title": "Sign-in failed",
  "status": 401,
  "detail": "Incorrect email or password.",
  "code": "AUTH",
  "subcode": "UNAUTHORIZED"
}
```

### `POST /api/auth/refresh`

```json
{ "refresh_token": "<refresh_token>" }
```

**200** with a new access token and a new refresh token. Store the new refresh token. Sending the previous refresh token again is **401**.

### `POST /api/auth/logout`

```json
{ "refresh_token": "<refresh_token>" }
```

**204** with an empty body. Refresh after logout is **401**.

### `GET /api/auth/me`

Header: `Authorization: Bearer <access_token>`.

**200**

```json
{
  "id": "da89e70a-87a5-4886-9ec5-0d64e9823ffb",
  "email": "sara@example.com",
  "name": "Sara Ali",
  "phone": "+971500000000",
  "role": "user"
}
```

No token, or a bad token, is **401** `Sign in to continue.`

## Chat

### `POST /api/chat`

This is the user-question API. Send `Authorization` when signed in. A guest does not need a header. Put the stored `anon-<uuid>` in `user_id`.

```json
{
  "message": "Show me 2 bedroom apartments for rent in Dubai Marina.",
  "session_id": "07210223-8119-4640-a01c-0071c3baa4e6",
  "user_id": "anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f",
  "focused_property_ids": [27351]
}
```

- `message` is required, 1–4000 characters after trim. Blank is **422** `Message is empty.`
- `session_id` is optional. Use the id from `POST /api/sessions/new`, or omit it and read `X-Thread-ID` from the response. It must be a UUID or letters and numbers, max 64 characters. The same rules apply to `thread_id` if a caller sends that name instead.
- `user_id` is optional. Send the guest id or `user.id`. If you omit it, the server uses the caller: the account id from the token, a usable `X-Visitor-ID`, or a newly minted visitor id. An invalid `user_id` is dropped and that caller id is used.
- `focused_property_ids` is optional. Up to 8 positive listing ids the user picked on screen, for a follow-up about those cards. Omit it on a normal question. Zero or a negative id is **422**.
- `session_profile` is optional. The server can echo it on `reply.reply`. Extra unknown fields are ignored.

**200** `Content-Type: text/event-stream`. Response header `X-Thread-ID` is the session id to store. The stream may start with a comment line `: ok`. Ignore lines that do not start with `event:` or `data:`.

A listing question returns events in this order. A greeting may skip `listings` and only send `text` then `done`.

```text
event: listings
data: {"ids":["27351"],"cards":[{"id":"27351","title_en":"2 Bedroom Apartment","slug":"2-bedroom-apartment","purpose":"for_rent","rental_period":"monthly","rooms":2,"baths":2,"area":1326,"completion_status":"ready","furnished":"furnished","type":"Apartment","address":"Dubai Marina","monthly_price":9500,"image_url":"https://example.com/photo.jpg","images":["https://example.com/photo.jpg"],"agency_name":"Example Realty","agent_name":"Example Agent"}]}

event: text
data: {"delta":"There are ","token":"There are "}

event: text
data: {"delta":"34 two-bedroom apartments","token":"34 two-bedroom apartments"}

event: reply
data: {"type":"reply","reply":{"intro_text":"There are 34 two-bedroom apartments for rent in Dubai Marina.","message_type":"listing_results","cards":[],"figures":null,"map":null,"show_map":false,"suggested_followups":["Show cheaper options"],"explainer":null,"building_pages":[],"question":null,"session_profile":null,"data_source_note":"","exclusions_note":""}}

event: done
data: {"thread_id":"07210223-8119-4640-a01c-0071c3baa4e6","route":"need_db","paused":false,"done":true}
```

Append every `text` `delta` to the message on screen. `token` is the same string.

`listings.cards[]` fields that may be present (empty ones are omitted):

`id`, `title_en`, `slug`, `purpose`, `rental_period`, `rooms`, `baths`, `area`, `completion_status`, `furnished`, `type`, `building_name`, `project_name`, `master_project_name`, `address`, `developer`, `is_distress`, `created_at`, `images`, `image_url`, `agency_name`, `agency_logo_url`, `agent_name`, `agent_image_url`, `price_min`, `price_max`, `yearly_price`, `monthly_price`, `weekly_price`, `daily_price`.

`id` on a card is a string. `focused_property_ids` and `property_id` on the contact route are numbers. Use the same digits.

`reply.reply` fields: `intro_text`, `message_type`, `cards`, `figures`, `map`, `show_map`, `suggested_followups`, `explainer`, `building_pages`, `question`, `session_profile`, `data_source_note`, `exclusions_note`. `message_type` is `recommendation`, `factual_answer`, `explanation`, or `listing_results`. `figures` is `null` or one object, not a list. Render `intro_text` if you did not already stream `text`. Use `suggested_followups` as chips. Use `listings.cards` for the property cards. `reply.reply.cards` can be empty because the cards already arrived on `listings`.

`done.route` is the router label (`need_db` when the answer came from the database). `done.paused` false means the turn finished. `done.done` is always true.

On failure the stream sends:

```text
event: error
data: {"detail":"I couldn't complete that reply.","error":"I couldn't complete that reply."}
```

Visitor chat is limited to 20 requests a minute. Signed-in chat is 60 a minute. Over the limit is **429**, with header `Retry-After` and `detail` “Too many attempts. Try again in N seconds.”

## Sessions

Session ids are UUIDs. A session appears in the list only after the first chat message, not when it is created.

### `POST /api/sessions/new`

No auth required. A bearer token is accepted and not used. Body can be `{}`.

```json
{ "session_id": "07210223-8119-4640-a01c-0071c3baa4e6", "carried_over": [] }
```

`previous_session_id`, `user_id`, and `carry_over_long_term` are accepted and ignored. The response `carried_over` is always `[]`.

### `GET /api/sessions?user_id=<caller>&limit=50`

Send the same `user_id` you use for chat. The server lists that id’s sessions and does not check the caller. A missing or invalid `user_id` returns `{ "sessions": [] }`. `limit` defaults to 30.

**200**

```json
{
  "sessions": [
    {
      "session_id": "07210223-8119-4640-a01c-0071c3baa4e6",
      "last_active": "2026-11-11T09:16:35.514551+00:00",
      "created_at": "2026-11-11T09:16:35.514551+00:00",
      "user_turns": 1,
      "title": "Show me 2 bedroom apartments for rent in Dubai Marina."
    }
  ]
}
```

### `GET /api/sessions/{session_id}/turns?limit=30`

The id must be a UUID or letters and numbers. A bad id is **404**. A valid id returns **200** even when the caller is not the owner and even when the chat is empty (`turns` is `[]`). **200**

```json
{
  "session_id": "07210223-8119-4640-a01c-0071c3baa4e6",
  "turns": [
    {
      "turn_id": "e104ad76-3ed8-433c-ab69-073cc43a6c4b",
      "ts": null,
      "user_message": "Show me 2 bedroom apartments for rent in Dubai Marina.",
      "assistant_message": "There are 34 two-bedroom apartments for rent in Dubai Marina.",
      "cards": [
        {
          "id": "27351",
          "title_en": "2 Bedroom Apartment",
          "purpose": "for_rent",
          "rooms": 2,
          "monthly_price": 9500
        }
      ],
      "envelope": null,
      "thumbs_up": false,
      "thumbs_down": false
    }
  ],
  "messages": [],
  "knowledge": {},
  "summary": ""
}
```

`cards` on a restored turn use the same card fields as `listings`.

### `POST /api/sessions/{session_id}/forget`

Body optional. **200**

```json
{ "status": "forgotten" }
```

The session then disappears from `GET /api/sessions`. A bad id is **404**. A usable id returns this body even when the sidebar had no such row.

### `POST /api/sessions/forget_many`

```json
{ "session_ids": ["07210223-8119-4640-a01c-0071c3baa4e6"] }
```

**200**

```json
{ "forgotten": ["07210223-8119-4640-a01c-0071c3baa4e6"] }
```

An id that is not a UUID or letters and numbers is left out of `forgotten`. The server does not check ownership. A usable id is deleted and listed even when it was not in that user’s sidebar.

### `POST /api/sessions/{session_id}/forget_all`

Forgets that session. When `user_id` is a valid id, also deletes that user’s long-term memory. The server does not check that `user_id` is the caller. Omit `user_id` to forget only the session.

```json
{ "user_id": "anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f" }
```

**200** `{ "status": "forgotten" }`

### `POST /api/sessions/{session_id}/claim`

Requires a bearer token. Moves a guest chat into the signed-in account. **401** without a token.

```json
{ "guest_user_id": "anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f" }
```

**200**

```json
{ "status": "ok", "claimed": true }
```

`claimed` is false when `guest_user_id` does not start with `anon-`, or when that guest id does not own the session. The response is still **200**.

### Quota and context are stubs

These respond, but they do not measure real usage. Do not block the UI on them.

`GET /api/sessions/{session_id}/quota`

```json
{ "used": 0, "limit": 100, "remaining": 100, "exhausted": false }
```

`GET /api/sessions/{session_id}/context`

```json
{ "prompt_tokens": 0, "budget": 0, "fraction": 0, "compacted_turns": 0 }
```

`POST /api/sessions/{session_id}/context/compact` returns the same object. It does not summarize the chat.

The session id must be a UUID or letters and numbers. A bad id is **404**.

## Preferences

Stored for 7 days in the shared cache, not in the account database.

`user_id` must be a UUID, letters and numbers, or `anon-<uuid>`. Anything else is **422** with `detail` “user_id is invalid.” The server does not check that this id is the caller. Send the same id you use for chat.

### `POST /api/preferences`

```json
{
  "user_id": "anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f",
  "preferences": { "purpose": "rent", "beds": 2, "area": "Dubai Marina" }
}
```

**200** The server merges keys into what is already stored.

```json
{
  "preferences": { "purpose": "rent", "beds": 2, "area": "Dubai Marina" }
}
```

### `GET /api/preferences?user_id=<caller>`

**200** `{ "preferences": { "purpose": "rent", "beds": 2, "area": "Dubai Marina" } }`

Nothing saved yet: `{ "preferences": null }`

### `DELETE /api/preferences?user_id=<caller>`

**200** `{ "status": "deleted" }`

The next GET returns `{ "preferences": null }`.

## Feedback

### `POST /api/feedback/thumbs`

Guest call or bearer token. Send `turn_id` from a restored turn, or both message strings. The server does not check that the caller owns the session. A body with no `turn_id` and no message text is **422**. If feedback storage is down, the response is **500**.

```json
{
  "thumbs": "up",
  "session_id": "07210223-8119-4640-a01c-0071c3baa4e6",
  "user_message": "Show me 2 bedroom apartments for rent in Dubai Marina.",
  "assistant_message": "There are 34 two-bedroom apartments for rent in Dubai Marina.",
  "comment": "Useful"
}
```

`thumbs` is `up` or `down`. You can send `turn_id` instead of the two message strings. `comment` is optional.

**200**

```json
{
  "ok": true,
  "turn_id": "e104ad76-3ed8-433c-ab69-073cc43a6c4b",
  "thumbs": "up"
}
```

Reload `GET /api/sessions/{session_id}/turns`. That turn then has `thumbs_up: true` or `thumbs_down: true`.

## Listing contact

### `GET /api/leads/property-contact?property_id=27351`

`property_id` is a positive integer, the card `id` as a number. No body.

**200**

```json
{
  "contact": {
    "property_id": 27351,
    "agent_id": 336,
    "agent_name": "Example Agent",
    "company_name": "Example Realty",
    "phone": "+971500000001",
    "mobile": null,
    "whatsapp": "+971500000001",
    "email": "agent@example.com",
    "verification_status": "approved",
    "contact_source": "agency"
  }
}
```

`contact_source` is `agency` or `listing_agent`. A phone, mobile, WhatsApp, or email field can be null. If none of them exist, the API returns **404** `No contact available for this listing.` Missing or zero `property_id` is **422**.

## Memory

The `user_id` in the path selects whose memory is read or deleted. Send the same id you use for chat. The server does not check it against the caller, and a different id is not **403**. If the memory store is not configured, the response is **500**.

### `GET /api/users/{user_id}/memory`

**200** A JSON array. A new guest has no memories:

```json
[]
```

Each item:

```json
{
  "id": "8d1c0b2a-1111-2222-3333-444455556666",
  "content": "Looking for a 2 bedroom rental in Dubai Marina.",
  "provenance": "explicit",
  "confidence": 0.9,
  "created_at": "2026-11-11T09:16:35.514551+00:00",
  "type": "preference",
  "cluster": "property_prefs"
}
```

### `DELETE /api/users/{user_id}/memory?cluster=property_prefs`

`cluster` or `memory_id` is required. Clusters: `property_prefs`, `budget`, `location`, `persona`, `goal`, `personal`, `work`, `travel`.

**200**

```json
{ "status": "deleted", "count": 1 }
```

Missing both query params, or an unknown cluster, is **422**.

`POST /api/sessions/{session_id}/forget_all` with the caller’s `user_id` deletes every cluster for that user and forgets the session.

## Do not call these

They are not on this service. Each returns **404**.

- `POST /api/chat/resume`
- `POST /api/chat/{runId}/cancel`
- `POST /api/realtime/voice-session`
- `GET /api/analytics/funnels`
- `GET /api/analytics/engagement`
- `POST /api/feedback/correction`
- `GET /api/feedback/stats`
- `GET /api/admin/eval-runs`
- `GET /api/admin/prompt-versions`
- `POST /api/leads/submit`
- `POST /api/leads/agents`
- `POST /api/leads/agents/dismiss`
- `POST /api/leads/cta-click`
- `GET /api/flows`
- Any WebSocket URL

The demo UI in this repo still calls some of these. A new frontend should not.

## Minimum integration

1. Store `anon-<uuid>` and send it as `user_id`. Do not use the response `X-Visitor-ID` as that id.
2. `POST /api/sessions/new`, then `POST /api/chat` with that `session_id` and the same `user_id`.
3. Render `text` deltas and `listings.cards`.
4. `GET /api/sessions?user_id=` for the sidebar and `GET /api/sessions/{session_id}/turns` to reopen a chat.
5. `GET /api/leads/property-contact?property_id=` for Call and WhatsApp.
6. Optional: register, login, refresh, logout, `GET /api/auth/me`, then `POST /api/sessions/{session_id}/claim` to keep the guest chat after sign-in.
