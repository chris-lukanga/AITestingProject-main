import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient
from app import create_app
from schemas.contracts import Target, Limits, RunRequest
from services.scenarios import demo_target
from services.security import enforce_scope, redact
from services.budget import estimate, Budget, BudgetExceeded
from services.offline_gateway import OfflineGateway
from agents.clarification_agent import ClarificationAgent
from agents.recommendation_agent import RecommendationAgent
from agents.test_generator_agent import TestGeneratorAgent
from agents.evaluation_agent import EvaluationAgent
from agents.report_agent import ReportAgent
from database.store import Store


def test_clarifications():
    agent=ClarificationAgent()
    target=Target()
    q=agent.questions(target)
    assert sum(x['essential'] for x in q)==2
    target=agent.apply(target,{'authorized':'Yes','endpoint':'http://127.0.0.1:8001/api/chat','tools':'Unknown','environment':'Unknown','data':['Unknown'],'purpose':'Synthetic audit'})
    assert not any(q['essential'] for q in agent.questions(target))
    assert target.clarification_answers['tools']=='Unknown'
    enforce_scope(target)


@pytest.mark.parametrize('ratio', [0,20,50,80,100])
def test_strategy_and_generation(ratio):
    target=Target.model_validate(demo_target())
    gateway=OfflineGateway()
    plan,_=gateway.generate_json('',json.dumps({'target':target.model_dump()}),purpose='platform_plan')
    cases,_=TestGeneratorAgent(gateway).generate(target.model_dump(),plan,10,ratio)
    assert len(cases)==10
    assert abs(sum(c['strategy']=='exploration' for c in cases)-round(10*ratio/100))<=1
    assert all(c['assertions'] for c in cases)
    recommendation=RecommendationAgent().recommend(target)
    assert recommendation['exploration']+recommendation['exploitation']==100
    assert recommendation['exploration']==max(0,min(100,sum(c['points'] for c in recommendation['contributions'])))


def test_historical_severity_changes_recommendation():
    target=Target.model_validate(demo_target())
    baseline=RecommendationAgent().recommend(target)['exploration']
    target.previous_failures=[{'severity':'critical','component':'RAG'}]*3
    assert RecommendationAgent().recommend(target)['exploration'] < baseline


def test_budget_warnings_and_hard_limits():
    target=Target.model_validate(demo_target())
    assert estimate(target,66,Limits())['warnings']
    assert not estimate(target,65,Limits())['warnings']
    assert not estimate(target,50,Limits(max_requests=1))['can_start']
    budget=Budget(Limits(max_requests=1))
    budget.reserve(10)
    with pytest.raises(BudgetExceeded):budget.reserve(10)


def test_price_unknown_blocks_metered_run():
    target=Target.model_validate(demo_target())
    target.adapter.kind='http'
    assert not estimate(target,50,Limits())['can_start']


@pytest.mark.parametrize('patch', [{'authorized':False},{'allowed_endpoints':['http://other.test']}])
def test_scope_rejected(patch):
    target=Target.model_validate(demo_target())
    target.testing_scope.update(patch)
    with pytest.raises(ValueError):enforce_scope(target)


def test_remote_scope_rejected(monkeypatch):
    monkeypatch.delenv('LAB_ALLOWED_ENDPOINTS',raising=False)
    target=Target.model_validate(demo_target('https://remote.invalid/chat'))
    target.adapter.kind='http'
    with pytest.raises(ValueError):enforce_scope(target)


def test_api_error_not_security_failure():
    gateway=OfflineGateway()
    plan,_=gateway.generate_json('',json.dumps({'target':demo_target()}),purpose='platform_plan')
    cases,_=TestGeneratorAgent(gateway).generate(demo_target(),plan,1,50)
    result=EvaluationAgent(gateway).evaluate(cases[0],{'turns':[{'outcome':'ERROR','response':'','status':503}]})
    assert result['classification']=='ERROR'


def wait_run(client,id,timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        run=client.get('/api/runs/'+id).json()
        if run['report'] and run['status'] not in ('running','created','paused'):
            return run
        time.sleep(0.05)
    pytest.fail('Run did not finish before timeout.')


def test_real_http_weak_hardened_history_and_reports(tmp_path,campus_url):
    ids=[]
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/api/health').status_code==200
        assert client.get('/').status_code==200
        for mode in ['weak','hardened']:
            t=client.post('/api/targets',json=demo_target(campus_url,mode)).json()
            assert not client.get(f"/api/targets/{t['id']}/clarifications").json()['questions']
            ratio=client.get(f"/api/targets/{t['id']}/recommendation").json()
            assert 'contributions' in ratio
            request={'target_id':t['id'],'exploration':50,'limits':{'requests_per_second':50,'concurrency':3}}
            assert client.post('/api/estimate',json=request).json()['can_start']
            created=client.post('/api/runs',json=request)
            assert created.status_code==201,created.text
            id=created.json()['id'];ids.append(id)
            assert client.post('/api/runs/'+id+'/start').status_code==200
            run=wait_run(client,id)
            assert run['status']=='completed',run['error']
            assert len(run['executions'])==10 and all(e['turns'][0]['status']==200 for e in run['executions'])
            assert run['report']['counts']['FAIL']==(8 if mode=='weak' else 0)
            assert run['report']['counts']['PASS']==(2 if mode=='weak' else 10)
            assert run['usage']['requests']==11
            assert run['usage']['tokens_observed']>0
            assert client.get('/api/runs/'+id+'/report?format=html').status_code==200
            assert (tmp_path/'reports'/id/'report.json').exists()
            events=client.get('/api/runs/'+id+'/events').text
            assert 'Evaluation Agent' in events and 'event: done' in events
        comparison=client.get(f'/api/compare?first={ids[0]}&second={ids[1]}').json()
        assert len(comparison['resolved'])==8 and not comparison['repeated']
    # New app and SQLite connections, no in-memory run state.
    with TestClient(create_app(tmp_path)) as restarted:
        assert len(restarted.get('/api/runs').json())==2
        assert restarted.get('/api/runs/'+ids[0]+'/report').json()['counts']['FAIL']==8


def test_cancel_and_pause(tmp_path,campus_url):
    with TestClient(create_app(tmp_path)) as client:
        t=client.post('/api/targets',json=demo_target(campus_url)).json()
        run=client.post('/api/runs',json={'target_id':t['id'],'limits':{'requests_per_second':1,'max_seconds':60}}).json()
        id=run['id']
        client.post('/api/runs/'+id+'/start')
        assert client.post('/api/runs/'+id+'/pause').status_code==200
        time.sleep(.2)
        assert client.get('/api/runs/'+id).json()['status']=='paused'
        assert client.post('/api/runs/'+id+'/resume').status_code==200
        time.sleep(.15)
        assert client.post('/api/runs/'+id+'/cancel').status_code==200
        finished=wait_run(client,id)
        assert finished['status']=='cancelled'
        assert finished['usage']['requests']<11
        assert sum(finished['report']['counts'].values())==len(finished['cases'])


def test_recovery_and_resume(tmp_path,campus_url):
    app=create_app(tmp_path)
    store=app.state.store
    target=Target.model_validate(demo_target(campus_url));target.id='target'
    store.put('target',target.id,target.model_dump())
    run=app.state.workflow.create(RunRequest(target_id='target',limits=Limits(requests_per_second=50)))
    gateway=OfflineGateway()
    plan,_=gateway.generate_json('',json.dumps({'target':target.model_dump()}),purpose='platform_plan')
    run.update(status='running',plan=plan,research={'research':[]})
    store.put('run',run['id'],run)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/api/runs/'+run['id']).json()['status']=='interrupted'
        assert client.post('/api/runs/'+run['id']+'/start').status_code==200
        completed=wait_run(client,run['id'])
        assert completed['status']=='completed'
        assert completed['plan']==plan


def test_origin_and_validation(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/api/targets',json={},headers={'Origin':'https://foreign.invalid'}).status_code==403
        assert client.post('/api/targets',json={'adapter':{'endpoint':'http://user:password@localhost/chat'}}).status_code==422
        assert client.post('/api/targets/import',json={'testing_scope':{'target_url':'http://user:password@localhost/chat'}}).status_code==422
        assert client.get('/api/runs/nonexistent').status_code==404


def test_redaction_persistence(tmp_path,monkeypatch):
    monkeypatch.setenv('TARGET_API_KEY','synthetic-secret-token')
    store=Store(tmp_path/'store.sqlite3')
    store.put('target','one',{'password':'private','message':'synthetic-secret-token'})
    saved=store.get('target','one')
    assert saved=={'password':'[REDACTED]','message':'[REDACTED]'}
