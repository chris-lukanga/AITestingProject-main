# LLM Integrity Lab

An evidence-based security testing workspace for applications that integrate language models, retrieval, memory and tools. Built on the existing AITestingProject planner and model gateway. The product name is configurable with `PRODUCT_NAME`.

The application includes a Python/FastAPI backend, a vanilla HTML/CSS/JavaScript interface, SQLite persistence, a shared Gemini/OpenRouter gateway, and a separate local target: **CampusHelp AI**. The full demonstration works without credentials or paid model calls.

## Problem and significance

Developers place LLMs between users, private documents, APIs and state-changing tools. Conventional testing remains necessary, but does not establish whether retrieved instructions alter an assistant, whether memory crosses identity boundaries, or whether a harmless question triggers a privileged tool. Probabilistic responses, changing models, provider failures and limited testing budgets make evidence difficult to reproduce.

This project turns target context and prior observations into objectives, structured cases, actual requests, evaluations and retained reports. Analysts can distinguish a confidentiality failure from a provider outage, retest fixes, identify missing coverage and account for resources.

## Research-backed motivation

IBM's July 29, 2026 announcement reports that more than 20% of studied organizations experienced breaches targeting AI models or applications. Separately, one quarter of malicious breaches were AI-enabled; those cost approximately $6 million on average, compared with a $4.99 million global breach average. AI-assisted attacks and attacks on AI systems are distinct measurements. The report covered 602 breached organizations during March 2025–February 2026; these are not population-wide vulnerability rates or evidence that this tool reduces breach costs. [IBM, 2026](https://newsroom.ibm.com/2026-07-29-ibm-study-one-in-four-malicious-breaches-are-ai-enabled,-costing-companies-6-million-on-average).

OWASP's 2026 edition describes risks spanning model inputs, sensitive context, retrieval, tools and downstream consumers. The platform uses identifiers from its official PDF, rather than retaining 2025 rankings. The resource page is dated August 3, 2026; the downloaded PDF still contains publication-date placeholders. [OWASP resource and download](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/).

NIST AI 600-1, published July 26, 2024, complements the AI Risk Management Framework with generative-AI risk guidance. Repeatable assessment, documented evidence and ongoing evaluation motivate retained history and decision traces. A report does not establish NIST compliance. [NIST publication](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence).

AgentDojo evaluates tool-using agents against untrusted material, with 97 realistic tasks and 629 security cases in the cited version. Its authors observe both utility failures and security failures, supporting separate reliability and vulnerability reporting. This demo is not an AgentDojo benchmark reproduction. [Debenedetti et al., 2024](https://arxiv.org/abs/2406.13352).

Newer work, AgentDyn, introduces 60 open-ended tasks and 560 injection cases across three application domains. Its February 3, 2026 preprint, revised May 7, evaluates ten defenses and discusses the tradeoff between security and blocking useful behavior. This supports retaining secure control cases alongside adversarial probes; the local CampusHelp suite does not reproduce these benchmarks. [Li et al., 2026](https://arxiv.org/abs/2602.03117).

References were checked on **October 8, 2026**. NIST also maintains [AI Technology Evaluation](https://pages.nist.gov/ai-technology-evaluation/) activities, but the requested Generative AI Profile remains the 2024 publication; evaluation programs are not substituted for risk-management guidance.

## Architecture and preserved modules

```text
Browser → FastAPI → Workflow coordinator → Shared model gateway / Tavily
                         ↓
Clarification → Planning → Generation → Execution → Evaluation → Reporting
                         ↓              ↓                       ↓
                  SQLite checkpoints   Authorized target HTTP   Next-run advice
                         ↓
                  SSE decision events → Browser
```

The target LLM and the platform's reasoning models are independent. Execution calls the target application's endpoint; a platform model's answer is never substituted for target evidence.

Preserved implementation:

- `backend/llm_gateway.py`: discovery, retries, fallback, context fingerprints, JSON parsing and history. Fixed OpenRouter answer parsing and zero-quota classification; added capacity checks, output bounds, redaction, budget hooks and decision events.
- `backend/web_research.py`: bounded Tavily research and URL deduplication; identical queries are deduplicated.
- `backend/agents/planner_agent.py`: original live research and planning, with authoritative 2026 mappings supplied to its prompt.
- `backend/orchestrator.py`: existing planning CLI, research file checkpoints and JSON outputs remain available.
- `backend/example.json`: retained unchanged. Import requires an exact executable endpoint and explicit scope; a historical root URL is not assumed to be a chat route.

The new `services/workflow.py` controls the complete web pipeline. `Store` provides a persistence boundary for a future PostgreSQL implementation; the current implementation is SQLite.

```text
AITestingProject-main/
├── main.py                        Compatibility CLI
├── run_lab.py                     Launch both websites
├── Start-Lab.cmd                   Windows launcher (works from PowerShell)
├── Start-Lab.ps1                   Optional PowerShell script launcher
├── requirements.txt
├── requirements-lock.txt          Verified dependency snapshot
├── .env.example
├── backend/
│   ├── app.py                     REST, SSE, static interface
│   ├── main.py / orchestrator.py   Preserved planning workflow
│   ├── llm_gateway.py / web_research.py
│   ├── example.json
│   ├── agents/
│   │   ├── clarification_agent.py / planner_agent.py
│   │   ├── test_generator_agent.py / execution_agent.py
│   │   ├── evaluation_agent.py / report_agent.py
│   │   └── recommendation_agent.py
│   ├── schemas/contracts.py       Validated configuration and cases
│   ├── database/store.py          SQLite documents, events, recovery
│   └── services/
│       ├── workflow.py / budget.py / allocation.py
│       ├── security.py / taxonomy.py
│       ├── history.py / http_contract.py
│       └── scenarios.py / offline_gateway.py
├── frontend/                      index.html, styles.css, app.js
├── examples/campushelp/            FastAPI backend and separate frontend
├── scripts/verify_demo.py          Actual HTTP and process restart verification
├── tests/                         Gateway, API, execution, browser checks
├── docs/                          API guide and verification record
└── outputs/                       Ignored runtime data and reports
```

## Agent responsibilities

| Agent | Responsibility |
|---|---|
| Clarification | Detect missing context; retain single/multiple/short/long answers; block missing authorization or exact endpoint scope. |
| Planning | Analyze target architecture, history, trust boundaries and research; produce objectives without attack strings. |
| Generation | Create validated, bounded, synthetic cases, assertions, priorities, estimates and strategy allocation. |
| Execution | Send real HTTP requests with sessions, multi-turn interactions, timing, tool observations, authentication, rate limits and concurrency. |
| Evaluation | Apply deterministic assertions first; use the shared gateway for subjective judgments; require a verifiable quote for subjective failures. |
| Reporting | Aggregate actual outcomes, coverage, reliability, regressions and remediation; save JSON and HTML. |
| Recommendation | Calculate transparent contributions from current failures, coverage, uncertainty, model changes and limits. |

Offline mode uses the same contracts through a shared deterministic gateway with bundled references. It is labeled offline evidence. Live mode reuses the existing planner, model gateway and Tavily; agents do not duplicate provider integrations.

## Exploration and focused retesting

The 0–100 slider specifies the intended exploration share of the **target-request budget**. The rest is focused validation/retesting. At low exploration the offline generator repeats established tests. Higher exploration can include more unique objectives when the case cap allows.

Multi-turn cases are indivisible. A subset-sum allocator assigns complete cases to the nearest requested request allocation. Actual planned percentages are stored and displayed. Ten cases requiring eleven requests at 50% round to five exploratory requests (45.5%) and six focused requests (54.5%). Shared planning overhead is outside that split. Token and cost shares can differ because inputs and responses have different sizes.

The recommended percentage is the clamped sum of its displayed contributions:

| Heuristic | Exploration contribution |
|---|---:|
| Baseline | +50 |
| Current high/critical historical failures | −8 each, capped at −30 |
| No completed prior coverage | +20 |
| Untested declared components | +3 each, capped at +15 |
| Unknown RAG/tool/memory fields | +5 each |
| Model differs from latest run | +15 |
| High-priority known failures | −2 each, capped at −10 |
| Monetary budget below $0.25 | −5 |
| Request ceiling below 20 | −5 |
| Runtime below 30 seconds | −5 |

The latest completed run describes current failures; resolved older failures remain in comparisons. Imported failure descriptions also influence planning. This is retained testing history, not model retraining. The heuristic is not scientifically validated and no general security score is claimed.

Exploration above 65% displays a cost warning. Preflight estimates show cases, requests, tokens, baseline runtime and approximate costs. Unknown metered pricing blocks execution until a conservative price ceiling is supplied. Free and discovered models are never assumed to have unlimited requests or usable quota.

## Authorization, budgets and evidence

- Explicit authorization and `testing_scope.allowed_endpoints` must identify the exact endpoint.
- Remote targets additionally require exact server-side `LAB_ALLOWED_ENDPOINTS` authorization and HTTPS. Redirects are disabled. CampusHelp is loopback-only.
- Credentials are environment-variable references. Embedded URL credentials, authorization/cookie headers and Host overrides cannot be persisted in adapter configuration.
- Secrets are redacted before storage and trace events. Generic target responses are omitted from decision events; full responses remain in the authorized analyst's detailed evidence.
- Retrieved research and target responses are untrusted data and are never executed as Python, shell commands or browser HTML.
- Each model attempt and target request reserves tokens/cost before dispatch. Generated cases receive a second budget preflight covering rendered payloads, repetitions and bounded conversation history. Excessive generated scope stops before target dispatch; explicitly adjust limits before resuming. Output limits, bounded response bytes, request timeouts and an overall deadline constrain work.
- Reservations are a conservative **dispatch budget**, not a guarantee about third-party invoices. Targets must honor configured output bounds; provider overhead and supplied pricing may differ. Reserved tokens and observed target tokens are distinguished.
- Pause stops future target dispatch at checkpoints. Submitted requests may finish. Cancel aborts target tasks; submitted synchronous provider work may finish, while subsequent dispatch is blocked.
- This release is a localhost single-analyst tool. Network deployment needs authentication, tenant isolation, encrypted retention and independent security review.

## Providers and setup

Gemini and OpenRouter power live reasoning; Tavily supplies research. Available text models are discovered, incompatible media models excluded and known capacity checked. Credential failures move to another provider; retired/404 models are skipped; 429/503 errors retry; explicit zero quota skips futile retries. OpenRouter can fall back from structured output to prompt-enforced, validated JSON. Full system/user context is preserved.

Provider indicators show configuration, not verified request success or quotas. Provider failure tests use mocks; the demonstrated end-to-end runs make no paid model calls.

Use a root `.env` or the existing `backend/.env`. Credentials do not need to be copied or changed. `.env.example` contains placeholders only.

```dotenv
PRODUCT_NAME=LLM Integrity Lab
LAB_DATA_DIR=./outputs/lab
GEMINI_API_KEY=your-server-side-value
OPENROUTER_API_KEY=your-server-side-value
TAVILY_API_KEY=your-server-side-value
OPENROUTER_ONLY_FREE=true
LAB_ALLOWED_ENDPOINTS=https://your-authorized-staging.example/api/chat
```

Python **3.12** is the verified runtime. Windows PowerShell, repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
# Copy .env.example to .env only if no root .env already exists.
.\.venv\Scripts\python.exe run_lab.py
```

Use `requirements.txt` to resolve compatible ranges instead of the tested snapshot. This workspace also has an ignored local runtime because system Python aliases were unusable:

```powershell
.\.runtime\python\python.exe run_lab.py
# Or choose .venv, then .runtime, then system Python automatically:
.\Start-Lab.cmd
```

`Start-Lab.cmd` works from PowerShell or Command Prompt without changing PowerShell's execution policy. If `Start-Lab.ps1` reports that running scripts is disabled, use `Start-Lab.cmd` or invoke Python directly as shown above. The `.ps1` launcher remains available on systems that permit PowerShell scripts. See [Microsoft's execution-policy documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies).

Open **http://127.0.0.1:8000** for the platform and **http://127.0.0.1:8001** for CampusHelp. The launcher checks both ports first. Healthy existing Lab servers are reused; launching twice reports their URLs and exits successfully. If one service is missing, only that service starts. An unrelated or unhealthy listener produces a clear port-conflict message. Ctrl+C stops only servers started by the current launcher; reused servers remain controlled by their original terminal. Separate startup:

```powershell
python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000
python -m uvicorn examples.campushelp.app:app --host 127.0.0.1 --port 8001
```

Use `--reload` for platform development. Repeatable local operation uses one worker without reload. Multiple ASGI workers are unsupported because background runs belong to one coordinator. The loopback middleware prevents treating this configuration as a publicly hosted production service.

The original planning CLI remains:

```powershell
python main.py backend/example.json
python main.py example.json   # Root compatibility shorthand
python main.py serve          # Platform only
```

The original planning CLI requires live provider and Tavily credentials. Use web offline mode or the demonstration script for complete no-cost execution.

## CampusHelp walkthrough

1. Launch both servers and choose **Try Demo**.
2. Confirm the endpoint is `http://127.0.0.1:8001/api/chat`, adapter is CampusHelp, mode is weak, and local scope is authorized.
3. Continue through clarification. The provided demo context needs no extra questions.
4. Review the recommendation; choose 50% for the reproducible comparison, offline reasoning and default limits.
5. Start the run. Live Testing displays real stages, queued cases, evaluations and streamed decisions.
6. Review findings and download JSON/HTML reports.
7. Try Demo again, choose hardened mode and repeat the 50% scope.
8. Compare runs in History and review resolved findings and next-run recommendations.

Synthetic scenarios cover cross-student retrieval, unintended ticket creation, ticket ownership parameters, shared memory, retrieved-document instructions, protected profile disclosure, hidden context exposure and an inert markup contract check. Public-policy and unsupported-guarantee checks are secure controls. The markup probe checks a declared plain-text contract; it does **not** demonstrate executable XSS, and both frontends render responses as text.

CampusHelp accepts explicit synthetic test identities instead of implementing production authentication. Hardened mode demonstrates deterministic application protections, not a claim that a real model is immune to injection.

## OWASP taxonomy and coverage

The official 2026 mapping is bundled in `services/taxonomy.py`:

| Identifier | Category |
|---|---|
| LLM01:2026 | Prompt Injection |
| LLM02:2026 | Sensitive Information Disclosure |
| LLM03:2026 | Excessive Agency |
| LLM04:2026 | Supply Chain |
| LLM05:2026 | Data and Model Poisoning |
| LLM06:2026 | Unbounded Consumption |
| LLM07:2026 | Misinformation |
| LLM08:2026 | Hidden Context Exposure |
| LLM09:2026 | Vector and Embedding Weaknesses |
| LLM10:2026 | Improper Output Handling |

Coverage counts categories with conclusive executed cases, not complete coverage within them. The standard demo covers seven categories. Supply-chain and poisoning reviews require extra artifact/administrative access and remain explicitly uncovered. An ordinary reliability probe is not a load test.

## API, persistence and recovery

Interactive docs: **http://127.0.0.1:8000/docs**. Schema: `/openapi.json`. Detailed routes and HTTP adapter contracts: [docs/API.md](docs/API.md).

SQLite retains targets, clarification answers, configurations, research, plans, cases, actual evidence, classifications, events, provider metadata, resource usage and recommendations. A restart marks running or paused runs interrupted. Resume keeps research/plans and provider history, skips evaluated cases, and can evaluate completed evidence without resending it. A resumed run clears its previous report until a new report is finalized. Cancelling an unstarted run also saves a zero-execution report. An interrupted request with no saved completion may need repeating; use synthetic, non-destructive inputs.

History is scoped to the application name and exact target endpoint. New cases receive a regression fingerprint from their normalized title, component, OWASP category and assertion contract. Equivalent assertions can match across changed generated IDs. Changed contracts remain separate; inconclusive or unexecuted checks never establish remediation. Older records without fingerprints retain their original ID matching.

Default files:

```text
outputs/lab/lab.sqlite3
outputs/lab/reports/<run-id>/report.json
outputs/lab/reports/<run-id>/report.html
outputs/verification/summary.json
outputs/verification/lab/reports/<run-id>/report.json
```

Settings retain default limits, model preference, free-model preference and retention. Pruning removes eligible database records; report files remain for deliberate archival. Databases, reports, checkpoints, screenshots, logs, runtime installations and credentials are ignored by Git.

## Testing and verified results

```powershell
python -m pytest -q
python scripts/verify_demo.py
# Also load the actually executed demo reports into the default browser workspace:
python scripts/verify_demo.py --seed-workspace
```

Playwright uses installed Google Chrome on this Windows workspace. Elsewhere run `python -m playwright install chromium` once, or set `BROWSER_EXECUTABLE`. Browser startup failures are reported, not substituted with fictional results.

Tests cover discovery, eligibility, fallback, 404/429/503, quota distinctions, context preservation, JSON validation, budget hooks, redaction, clarification, recommendations, allocation, estimates, scope, real HTTP execution, evaluation, reports, persistence, recovery, pause/cancel, origin restrictions and browser operation. Additional regressions exercise generic conversation history, identity credentials, expected HTTP denials, nested response observations, changed case IDs, stopped-run reports and a mocked live planning pipeline that still calls the actual CampusHelp server.

The independent process-level script launches both servers, runs weak/hardened targets, writes reports, stops the platform, starts a new process and reloads both reports. At 50% and ten cases:

| Mode | Cases | Actual requests | PASS | FAIL | ERROR | Paid calls |
|---|---:|---:|---:|---:|---:|---:|
| Weak | 10 | 11 | 2 | 8 | 0 | 0 |
| Hardened | 10 | 11 | 10 | 0 | 0 | 0 |

Browser tests exercise target configuration, all four clarification controls, live slider values/warnings, estimates, pause/resume, execution, traces, evidence, downloads, research, comparison, settings and a 390px mobile viewport. The final test count and measured process-run IDs are recorded in [docs/VERIFICATION.md](docs/VERIFICATION.md).

These are fixture results, not real-model attack-success rates. A PASS establishes only the tested assertion. ERROR and INCONCLUSIVE remain separate from vulnerabilities. Subjective judgment can still be mistaken despite requiring evidence quotes.

## Potential impact and limitations

The platform can reduce repeated manual execution, prioritize observed failures, surface regressions after updates, document coverage gaps and preserve auditable evidence. Reliability and cost records help separate security testing from provider troubleshooting.

Hypothetical example: 20 cases at 8 minutes each take 160 minutes manually. Assuming 10 minutes of automated execution and 30 minutes of analyst review, the scenario saves 120 minutes (75%). At an assumed $60/hour this is $120 per run. These are illustrative assumptions, not experimentally proven savings; setup, authoring and remediation costs are excluded.

Current limits include a finite synthetic catalog, unknown production-model behavior, approximate prices, cooperative provider cancellation, locally stored evidence, and no multi-user authentication or encrypted database. Generic offline HTTP cases execute but remain INCONCLUSIVE without target-specific assertions or a live judge. No underlying model is trained or fine-tuned.

## Roadmap

1. Extend target-specific canary fixtures, reviewed assertions and identity protocols beyond the current per-user environment references.
2. Verify live providers/Tavily against controlled staging targets with measured quotas and prices.
3. Add model-specific tokenizers and billing reconciliation.
4. Implement protected multi-user deployment, encrypted retention, distributed jobs and PostgreSQL persistence.
5. Extend artifact/supply-chain reviews, poisoning fixtures, adaptive variants and benchmark comparisons.

## References

1. IBM. (2026, July 29). *IBM Study: One in Four Malicious Breaches are AI-Enabled, Costing Companies $6 Million on Average.* [Announcement](https://newsroom.ibm.com/2026-07-29-ibm-study-one-in-four-malicious-breaches-are-ai-enabled,-costing-companies-6-million-on-average).
2. OWASP GenAI Security Project. (2026, August 3 resource date). *OWASP GenAI LLM Top 10 2026.* [Resource](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/), [official PDF](https://genai.owasp.org/download/56857/?tmstv=1785822482). Category names attributed to OWASP under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); no OWASP endorsement is claimed.
3. Autio, C., Schwartz, R., Dunietz, J., Jain, S., Stanley, M., Tabassi, E., Hall, P., & Roberts, K. (2024, July 26). *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile.* NIST AI 600-1. [DOI](https://doi.org/10.6028/NIST.AI.600-1).
4. Debenedetti, E., Zhang, J., Balunović, M., Beurer-Kellner, L., Fischer, M., & Tramèr, F. (2024, June 19 initial version; November 24 revision). *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents.* [arXiv:2406.13352](https://arxiv.org/abs/2406.13352).
5. Li, H., Wen, R., Shi, S., Zhang, N., Vorobeychik, Y., & Xiao, C. (2026, February 3 initial version; May 7 revision). *AgentDyn: Are Your Agent Security Defenses Deployable in Real-World Dynamic Environments?* Preprint. [arXiv:2602.03117](https://arxiv.org/abs/2602.03117).
