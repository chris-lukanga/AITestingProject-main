import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
load_dotenv(ROOT / 'backend' / '.env')
from schemas.contracts import Target, RunRequest, Limits
from database.store import Store
from services.workflow import Workflow
from services.scenarios import demo_target
from services.budget import estimate
from agents.clarification_agent import ClarificationAgent
from agents.recommendation_agent import RecommendationAgent
from agents.report_agent import ReportAgent
from services.history import same_target, compare_evaluations


class EstimateRequest(BaseModel):
    target_id: str
    exploration: int = Field(default=50, ge=0, le=100)
    limits: Limits = Field(default_factory=Limits)
    mode: Literal['offline', 'live'] = 'offline'


class Settings(BaseModel):
    mode: Literal['offline', 'live'] = os.getenv('LAB_MODE', 'offline')
    default_limits: Limits = Field(default_factory=Limits)
    retention_days: int = Field(default=90, ge=1, le=3650)
    preferred_model: str = os.getenv('GEMINI_MODEL', '')
    only_free: bool = os.getenv('OPENROUTER_ONLY_FREE', 'true').lower() == 'true'


def create_app(data_dir=None):
    data_dir = Path(data_dir or os.getenv('LAB_DATA_DIR', ROOT / 'outputs' / 'lab'))
    store = Store(data_dir / 'lab.sqlite3')
    workflow = Workflow(store, data_dir / 'reports')
    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        yield
        await workflow.shutdown()
    app = FastAPI(title=os.getenv('PRODUCT_NAME', 'LLM Integrity Lab'), version='1.0.0', lifespan=lifespan)
    app.state.store, app.state.workflow = store, workflow

    @app.middleware('http')
    async def local_browser_boundary(request: Request, call_next):
        # Reject cross-origin browser mutations, including DNS rebinding Host values.
        host = request.url.hostname
        if host not in ('127.0.0.1', 'localhost', '::1', 'testserver'):
            return HTMLResponse('This local platform accepts loopback hostnames only.', status_code=403)
        origin = request.headers.get('origin')
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin != str(request.base_url).rstrip('/'):
            return HTMLResponse('Cross-origin writes are not allowed.', status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        if request.url.path in ('/docs', '/redoc'):
            # FastAPI's documentation pages load their official documentation UI.
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' https://fastapi.tiangolo.com data:; frame-ancestors 'none'"
        return response

    def get(kind, id):
        value = store.get(kind, id)
        if value is None:
            raise HTTPException(404, f'{kind.title()} not found.')
        return value

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'service': 'llm-integrity-lab', 'product': app.title}

    @app.get('/api/demo-target')
    def demo(mode: str = 'weak'):
        if mode not in ('weak', 'hardened'):
            raise HTTPException(422, 'Invalid demo mode.')
        return demo_target(mode=mode)

    @app.get('/api/example')
    def example():
        return json.loads((ROOT / 'backend' / 'example.json').read_text(encoding='utf-8'))

    @app.get('/api/targets')
    def targets():
        return store.list('target')

    @app.post('/api/targets', status_code=201)
    @app.post('/api/targets/import', status_code=201)
    def target_create(target: Target):
        target.id = target.id or uuid.uuid4().hex
        store.put('target', target.id, target.model_dump())
        return get('target', target.id)

    @app.get('/api/targets/{id}')
    def target_get(id: str):
        return get('target', id)

    @app.get('/api/targets/{id}/clarifications')
    def questions(id: str):
        return {'questions': ClarificationAgent().questions(Target.model_validate(get('target', id)))}

    @app.post('/api/targets/{id}/clarifications')
    def answers(id: str, answers: dict):
        try:
            target = ClarificationAgent().apply(Target.model_validate(get('target', id)), answers)
            store.put('target', id, target.model_dump())
            return {'target': get('target', id), 'questions': ClarificationAgent().questions(target)}
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/api/targets/{id}/recommendation')
    def recommendation(id: str):
        target = Target.model_validate(get('target', id))
        settings = store.get('settings', 'default') or Settings().model_dump()
        return RecommendationAgent().recommend(target, workflow.history(target.model_dump()), Limits.model_validate(settings['default_limits']))

    @app.post('/api/estimate')
    def estimated(config: EstimateRequest):
        if config.mode not in ('offline', 'live'):
            raise HTTPException(422, 'Mode must be offline or live.')
        return estimate(Target.model_validate(get('target', config.target_id)), config.exploration, config.limits, config.mode)

    @app.post('/api/runs', status_code=201)
    def run_create(config: RunRequest):
        try:
            return workflow.create(config)
        except KeyError as error:
            raise HTTPException(404, str(error))
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get('/api/runs')
    def runs():
        return [{k: r[k] for k in ['id', 'status', 'stage', 'created_at', 'updated_at', 'config', 'usage', 'estimate']} |
                {'target_name': r['target']['application'].get('name'), 'report': {'counts': r['report']['counts'], 'assessment': r['report']['assessment']} if r['report'] else None,
                 'completed': len(r['evaluations']), 'planned': len(r['cases']), 'providers': sorted({e.get('provider', '') for e in r['provider_history']})} for r in store.list('run')]

    @app.get('/api/runs/{id}')
    def run_get(id: str):
        return get('run', id)

    @app.patch('/api/runs/{id}/limits')
    def run_limits(id: str, limits: Limits):
        run = get('run', id)
        if run['status'] not in ('created', 'interrupted', 'failed', 'limited'):
            raise HTTPException(409, 'Change limits only while the run is stopped.')
        run['config']['limits'] = limits.model_dump()
        run['estimate'] = estimate(Target.model_validate(run['target']), run['config']['exploration'], limits, run['config']['mode'])
        if not run['estimate']['can_start']:
            raise HTTPException(422, run['estimate']['violations'])
        store.put('run', id, run)
        return run

    @app.get('/api/activity')
    def activity():
        events = [dict(event, run_id=run['id']) for run in store.list('run')[:5] for event in store.events(run['id'])]
        return {'events': sorted(events, key=lambda e: e['timestamp'], reverse=True)[:12]}

    @app.post('/api/runs/{id}/{action}')
    async def run_action(id: str, action: str):
        try:
            return workflow.action(id, action)
        except KeyError as error:
            raise HTTPException(404, str(error))
        except ValueError as error:
            raise HTTPException(409, str(error))

    @app.get('/api/runs/{id}/cases')
    def cases(id: str):
        return {'cases': get('run', id)['cases']}

    @app.get('/api/runs/{id}/findings')
    def findings(id: str):
        return {'findings': [e for e in get('run', id)['evaluations'] if e['classification'] == 'FAIL']}

    @app.get('/api/runs/{id}/research')
    def research(id: str):
        run = get('run', id)
        return {'research': run['research'], 'plan': run['plan']}

    @app.get('/api/runs/{id}/events')
    async def events(id: str, request: Request, after: int = 0, agent: str = '', severity: str = '', stage: str = ''):
        get('run', id)
        try:
            after = max(after, int(request.headers.get('last-event-id', 0)))
        except ValueError:
            raise HTTPException(422, 'Invalid event cursor.')
        async def stream():
            cursor = after
            while not await request.is_disconnected():
                for event in store.events(id, cursor):
                    cursor = event['seq']
                    if (not agent or agent == event['agent']) and (not severity or severity == event['severity']) and (not stage or stage == event['stage']):
                        yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
                run = get('run', id)
                if run['report'] and run['status'] in ('completed', 'failed', 'cancelled', 'limited', 'interrupted'):
                    yield 'event: done\ndata: {}\n\n'
                    break
                yield ': heartbeat\n\n'
                await asyncio.sleep(0.5)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @app.get('/api/runs/{id}/report')
    def report(id: str, format: str = 'json', download: bool = False):
        run = get('run', id)
        if not run['report']:
            raise HTTPException(409, 'Report is not available yet.')
        if format not in ('json', 'html'):
            raise HTTPException(422, 'Report format must be json or html.')
        if download:
            path = workflow.output_dir / id / f'report.{format}'
            if not path.exists():
                # SQLite is authoritative; downloads can be rebuilt after report-file loss.
                path.parent.mkdir(parents=True, exist_ok=True)
                content = ReportAgent().html(run['report'], app.title) if format == 'html' else json.dumps(run['report'], indent=2)
                path.write_text(content, encoding='utf-8')
            return FileResponse(path, filename=f'{id}.{format}')
        return HTMLResponse(ReportAgent().html(run['report'], app.title)) if format == 'html' else run['report']

    @app.get('/api/compare')
    def compare(first: str, second: str):
        a, b = get('run', first), get('run', second)
        if not same_target(a['target'], b['target']):
            raise HTTPException(422, 'Compare runs of the same target.')
        if not a['report'] or not b['report']:
            raise HTTPException(409, 'Both reports must be available.')
        return {'first': first, 'second': second, **compare_evaluations(a['evaluations'], b['evaluations']),
                'counts': [a['report']['counts'], b['report']['counts']]}

    @app.get('/api/providers')
    def providers():
        return {'offline': {'available': True, 'model': 'deterministic-rules-v1'},
                'gemini': {'configured': bool(os.getenv('GEMINI_API_KEY')), 'availability': 'Not verified; discovered models can still have no quota'},
                'openrouter': {'configured': bool(os.getenv('OPENROUTER_API_KEY')), 'availability': 'Not verified; free models have quotas'},
                'tavily': {'configured': bool(os.getenv('TAVILY_API_KEY'))}}

    @app.get('/api/settings')
    def settings_get():
        return dict(store.get('settings', 'default') or Settings().model_dump(), product=app.title,
                    allowed_endpoints=[x for x in os.getenv('LAB_ALLOWED_ENDPOINTS', '').split(',') if x])

    @app.put('/api/settings')
    def settings_put(settings: Settings):
        store.put('settings', 'default', settings.model_dump())
        return settings_get()

    @app.post('/api/maintenance/prune')
    def prune():
        settings = store.get('settings', 'default') or Settings().model_dump()
        count = store.prune(settings['retention_days'])
        return {'deleted_runs': count, 'note': 'Downloaded report files are retained on disk; remove them separately when no longer needed.'}

    app.mount('/assets', StaticFiles(directory=ROOT / 'frontend'), name='assets')
    @app.get('/', response_class=FileResponse)
    def index():
        return FileResponse(ROOT / 'frontend' / 'index.html')
    return app


app = create_app()
