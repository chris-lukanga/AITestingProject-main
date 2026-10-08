# API and adapter guide

Authoritative schemas and constraints are at `/docs` and `/openapi.json`. Routes below use the `/api` prefix. Errors return `detail`: 404 for missing records, 422 for invalid configuration and 409 for state conflicts.

| Method | Path | Behavior |
|---|---|---|
| GET | `/health` | Product identity and backend status |
| GET | `/demo-target?mode=weak` | Authorized synthetic demo configuration |
| GET | `/example` | Existing example.json |
| GET / POST | `/targets` | List / save validated target |
| POST | `/targets/import` | Import target JSON |
| GET | `/targets/{id}` | Stored target |
| GET / POST | `/targets/{id}/clarifications` | Missing questions / apply answers |
| GET | `/targets/{id}/recommendation` | Ratio and heuristic contributions |
| POST | `/estimate` | Preflight warnings and estimates |
| GET / POST | `/runs` | History / create run |
| GET | `/runs/{id}` | Full run progress and evidence |
| POST | `/runs/{id}/start`, `/pause`, `/resume`, `/cancel` | Control workflow |
| PATCH | `/runs/{id}/limits` | Explicit limit change on stopped run |
| GET | `/runs/{id}/events` | Persistent SSE stream |
| GET | `/runs/{id}/cases`, `/findings`, `/research` | Cases, failures and sources/plan |
| GET | `/runs/{id}/report` | JSON; `format=html` and `download=true` supported |
| GET | `/compare?first={id}&second={id}` | Repeated/new/resolved/not-retested failures |
| GET | `/activity`, `/providers` | Decisions / configured provider indicators |
| GET / PUT | `/settings` | Limits, model preferences and retention |
| POST | `/maintenance/prune` | Prune expired terminal run records |

## HTTP target configuration

Existing architecture sections are preserved. Execution additionally requires an adapter and exact scope.

```json
{
  "application": {"name": "Authorized staging assistant", "purpose": "Synthetic support testing"},
  "llm": {"provider": "Target provider", "model": "Target model"},
  "integration": {"rag_enabled": true, "tools_enabled": false, "conversation_memory": true},
  "testing_scope": {
    "authorized": true,
    "environment": "Authorized staging",
    "allowed_endpoints": ["https://staging.example/api/chat"]
  },
  "adapter": {
    "kind": "http",
    "endpoint": "https://staging.example/api/chat",
    "request_template": {
      "messages": "{messages}",
      "session_id": "{session}",
      "max_tokens": "{max_tokens}"
    },
    "response_path": "choices.0.message.content",
    "tool_calls_path": "choices.0.message.tool_calls",
    "usage_path": "usage",
    "provider_path": "provider",
    "model_path": "model",
    "headers": {"Content-Type": "application/json"},
    "auth_env": "STAGING_TARGET_API_KEY",
    "auth_header": "Authorization",
    "auth_prefix": "Bearer ",
    "max_response_bytes": 65536
  }
}
```

Set `LAB_ALLOWED_ENDPOINTS=https://staging.example/api/chat` and the authentication variable server-side. Templates recursively substitute `{input}`, `{session}`, `{user}`, `{mode}`, `{max_tokens}` and `{messages}`. A placeholder occupying the whole value retains its type. `{messages}` supplies user/assistant conversation history, including the current input. Literal placeholder text inside test inputs is preserved. Dot paths support dictionary keys and numerical array indices. A session stays stable within one repetition and changes between cases/repetitions. This adapter supports POST/JSON responses; streaming targets need a non-streaming application endpoint.

For cross-user tests, configure `auth_env_by_user`, for example `{"tenant-a":"AUDIT_A_KEY","tenant-b":"AUDIT_B_KEY"}`. These values are variable names, never tokens. Each test turn selects its declared identity and authentication reference; an undeclared identity cannot dispatch. A shared session can test server-side ownership, while `{messages}` retains separate histories per identity so the client does not introduce artificial cross-user leakage. Without this mapping, `auth_env` applies to all turns. Changing the `{user}` request field alone is not proof of authenticated tenant isolation.

Observations default to `tool_calls`, `usage`, `provider` and `model`. Override their paths for a nested API response. Missing tool observations yield INCONCLUSIVE for tool assertions. An expected access-control denial can use `{"kind":"http_status","value":403}` in a case's assertions; observed 403 is PASS, an unexpected 200 is FAIL, and a 503 remains ERROR. Non-JSON responses and transport failures remain ERROR. Marker assertions require nonempty values.

No redirects, URL credentials, Host overrides or credential-bearing headers are accepted. CampusHelp canaries and identities must not be interpreted as facts about unrelated targets.

## Run request

```json
{
  "target_id": "saved-target-id",
  "exploration": 50,
  "mode": "offline",
  "limits": {
    "max_tests": 10,
    "max_requests": 60,
    "max_tokens": 100000,
    "budget_usd": 1,
    "max_seconds": 120,
    "concurrency": 2,
    "requests_per_second": 5,
    "timeout_seconds": 10,
    "max_output_tokens": 1024,
    "price_per_million": null
  }
}
```

The same configuration shape works for `/estimate`. `mode` selects platform reasoning, separately from the target. Offline CampusHelp has no provider cost. Other targets or live reasoning need a conservative USD price ceiling per million combined input/output tokens. This is approximate user-supplied pricing.

Reservations count failed attempts and retries and include serialized target inputs as well as the output bound. Before dispatch, generated cases are checked against the remaining request, token and monetary limits; conversation history is conservatively bounded by `max_response_bytes`. Generic/live initial estimates are approximate; the offline CampusHelp estimate uses the bundled cases' actual request counts. Usage records distinguish `target_requests`, `model_requests`, target `tokens_observed` and `model_tokens_observed` when provider usage is available.

Known model context limits filter candidates; unknown router capacity is not described as verified. Model preferences are captured independently by each run's gateway. Resume skips evaluated cases and reuses completed evidence, keeps prior provider attempts, clears the previous report and opens a fresh event stream in the browser. A stopped run can receive an explicit new limits object with PATCH before resuming. Cancelling a run before execution still creates downloadable reports.

Run comparisons require the same application name and exact endpoint. Matching assertion contracts use a persistent regression fingerprint; inconclusive and skipped checks are listed as not retested rather than resolved. Report downloads can be rebuilt from SQLite if report files were removed.

States: `created`, `running`, `paused`, `completed`, `cancelled`, `limited`, `failed`, `interrupted`. Paused runs retain their overall deadline. Evaluation outcomes: `PASS`, `FAIL`, `INCONCLUSIVE`, `ERROR`, `SKIPPED`.

## SSE and downloads

Connect to `/runs/{id}/events?after=0&agent=Planning%20Agent&severity=info&stage=planning`. Filters are optional and exact. Each event has an integer id and a JSON object. Reconnects support `Last-Event-ID`; heartbeat comments keep connections alive and `done` ends terminal streams. Events can replay after restart.

Events include agent, task/stage, target summary, decision, explanation, evidence summary, provider/model, fallback, confidence when available, result and timestamp. These are concise audit summaries, never hidden provider reasoning. Generic target response text is omitted from the trace.

JSON/HTML downloads become available after report persistence. Observed text is escaped in HTML reports.

## PowerShell quick check

```powershell
$base = 'http://127.0.0.1:8000/api'
$target = Invoke-RestMethod "$base/demo-target"
$saved = Invoke-RestMethod "$base/targets" -Method Post -ContentType 'application/json' -Body ($target | ConvertTo-Json -Depth 20)
$config = @{ target_id = $saved.id; exploration = 50; mode = 'offline' }
$run = Invoke-RestMethod "$base/runs" -Method Post -ContentType 'application/json' -Body ($config | ConvertTo-Json -Depth 20)
Invoke-RestMethod "$base/runs/$($run.id)/start" -Method Post
Invoke-RestMethod "$base/runs/$($run.id)"
```
