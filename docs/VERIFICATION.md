# Verification record

Verified October 8, 2026, on Windows using the ignored project-local Python 3.12.10 runtime and `requirements-lock.txt`.

Provider failure tests use deterministic mocks. No paid model calls were made. Bundled references are labeled offline. CampusHelp findings derive from actual HTTP responses.

The suite exercises gateway behavior, API contracts, real HTTP weak/hardened execution, persistence, recovery, authorization, budgets, cancellation and headless Chrome/Playwright. A separate script launches processes, saves reports, restarts the platform and reloads history.

Expected reproducible ten-case demo: weak = 2 PASS / 8 FAIL; hardened = 10 PASS / 0 FAIL; eleven real requests each. One failed check concerns an inert plain-text output contract and does not establish executable XSS.

Original full implementation check: **84 passed, 0 failed, 1 warning**, in **41.82 seconds** using:

```powershell
.\.runtime\python\python.exe -m pytest -q
```

The warning is Starlette's deprecation of its TestClient HTTPX compatibility path. It does not affect the passing checks; dependency migration is deferred until the HTTPX2 path is reviewed and pinned.

The three Playwright tests exercised the complete platform workflow, including pause/resume and restarted SSE streaming; all four clarification controls; CampusHelp chat/identity/mode changes; downloads; settings; and a 390px viewport.

The final independent process verification used:

```powershell
.\.runtime\python\python.exe scripts\verify_demo.py --seed-workspace
```

| Mode | Run ID | PASS | FAIL | ERROR | Actual target requests | Observed target tokens | Elapsed seconds |
|---|---|---:|---:|---:|---:|---:|---:|
| Weak | `2cbfddd9c5df477980d19c3d30251b71` | 2 | 8 | 0 | 11 | 256 | 3.984 |
| Hardened | `43cb26cc321f459fa1d35a8025f0f798` | 10 | 0 | 0 | 11 | 296 | 3.250 |

Both modes had zero inconclusive/skipped outcomes and zero paid model calls. The comparison found **8 resolved, 0 repeated and 0 new failures**. Both reports loaded after terminating the platform and starting a new process with the same SQLite database.

The weak run's next recommendation was **10% exploration / 90% focused retesting**. After hardened verification the recommendation was **50% / 50%**. Contributions are retained in each report; these are heuristic recommendations, not validated security scores.

Saved default-workspace reports:

```text
outputs/lab/reports/2cbfddd9c5df477980d19c3d30251b71/report.json
outputs/lab/reports/2cbfddd9c5df477980d19c3d30251b71/report.html
outputs/lab/reports/43cb26cc321f459fa1d35a8025f0f798/report.json
outputs/lab/reports/43cb26cc321f459fa1d35a8025f0f798/report.html
outputs/verification/summary.json
outputs/browser-overview.png
```

Additional tests confirm cancellation before task startup, report regeneration from SQLite, recovery of paused runs, evaluation of saved HTTP evidence without resending, model-preference isolation, generated-budget rejection before dispatch, authenticated identity switching, nested API observations, explicit access-control denials, changed case identifiers, custom credential redaction and malformed judge handling. The original `python main.py example.json` route was exercised twice with mocked research/planning: it reused its research checkpoint and saved redacted plan, metadata and gateway history files. A mocked live-agent integration test exercises the shared gateway with actual CampusHelp HTTP execution; it is not evidence of successful calls to external providers.

Provider fallback, discovery, retries, JSON parsing and quota errors were tested with mocked Gemini/OpenRouter responses. Live provider quotas, live Tavily searches, current billing and production-model security have **not** been verified. Research sources and the official OWASP 2026 taxonomy were separately checked on the web and are cited in the README.

`git check-ignore` confirmed that the runtime installation, SQLite database, reports/checkpoints, verification output and environment files are excluded. Generated evidence is under `outputs/` and is ignored by Git.

The normal `run_lab.py` launcher was also exercised at its documented ports. `/api/health` and HTML returned HTTP 200 for the platform on port 8000 and CampusHelp on port 8001. Headless Chrome loaded the default workspace overview and saved run history. `pip check` reported no broken requirements.

After PowerShell blocked `Start-Lab.ps1` under the user's execution policy, `Start-Lab.cmd` was added and verified. It selected the project-local Python runtime and launched both servers; both health endpoints and both website pages returned HTTP 200. The verification process tree was stopped afterward, leaving ports 8000 and 8001 available. No execution-policy settings were changed.

The launcher was subsequently made safe to repeat after a user encountered occupied ports. It now identifies healthy existing Lab servers, starts only missing services, checks readiness before reporting success, and reports unrelated port conflicts without a launcher traceback. Cleanup stops only processes created by that invocation. Real-process regressions cover repeated startup, partial startup, preservation of unrelated listeners and startup failure. Running `Start-Lab.cmd` against the user's healthy servers returned exit code 0 and printed both existing URLs; both health checks remained HTTP 200.

Follow-up verification after the launcher fix: the expanded full suite returned **85 passed and 3 browser-startup failures** in 60.56 seconds, with the existing dependency warning. All three failures occurred before browser assertions with `Connection closed while reading from the driver`. The browser suite was rerun separately and **all 3 passed in 15.90 seconds**. All **88 checks**, including four real-process launcher regressions, therefore passed across the full run and browser rerun. No execution policy or existing server process was changed by the launcher verification.
