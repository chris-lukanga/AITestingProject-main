"""Stopped-run, adapter and evidence regressions discovered in the final audit."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace as Obj
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

import llm_gateway as gateway_module
from app import create_app
from agents.evaluation_agent import EvaluationAgent
from agents.execution_agent import ExecutionAgent, render
from agents.test_generator_agent import TestGeneratorAgent
from schemas.contracts import Target, Limits, RunRequest, Assertion, Adapter
from services.budget import Budget, BudgetExceeded, estimate, enforce_generated_budget
from services.history import compare_evaluations
from services.offline_gateway import OfflineGateway
from services.scenarios import demo_target
from services.security import redact
from tests.test_adapters import single_case
from tests.test_platform import wait_run


def test_cancel_before_start_saves_report_and_ends_stream(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        target = client.post('/api/targets', json=demo_target()).json()
        run = client.post('/api/runs', json={'target_id': target['id']}).json()
        cancelled = client.post(f"/api/runs/{run['id']}/cancel").json()
        assert cancelled['status'] == 'cancelled'
        assert cancelled['report']['tests_executed'] == 0
        assert 'event: done' in client.get(f"/api/runs/{run['id']}/events").text
        assert client.get(f"/api/runs/{run['id']}/report?download=true").status_code == 200


async def test_cancel_before_background_task_enters_run(tmp_path):
    app = create_app(tmp_path)
    target = Target.model_validate(demo_target())
    target.id = 'target'
    app.state.store.put('target', target.id, target.model_dump())
    run = app.state.workflow.create(RunRequest(target_id=target.id))
    app.state.workflow.action(run['id'], 'start')
    app.state.workflow.action(run['id'], 'cancel')
    await app.state.workflow.shutdown()
    finished = app.state.store.get('run', run['id'])
    assert finished['status'] == 'cancelled' and finished['report']
    assert finished['usage']['requests'] == 0


def test_resume_evaluates_saved_http_evidence_without_resending(tmp_path, campus_url):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        target = client.post('/api/targets', json=demo_target(campus_url)).json()
        run = client.post('/api/runs', json={'target_id': target['id'], 'limits': {'max_tests': 1, 'max_requests': 1}}).json()
        client.post(f"/api/runs/{run['id']}/start")
        first = wait_run(client, run['id'])
        assert len(first['executions']) == 1
        prior_history = deepcopy(first['provider_history'])
        first.update(status='failed', evaluations=[])
        app.state.store.put('run', run['id'], first)
        restarted = client.post(f"/api/runs/{run['id']}/resume").json()
        assert restarted['report'] is None
        completed = wait_run(client, run['id'])
        assert completed['status'] == 'completed'
        assert completed['usage']['requests'] == 1
        assert len(completed['executions']) == 1 and len(completed['evaluations']) == 1
        assert completed['provider_history'][:len(prior_history)] == prior_history
        report_file = tmp_path / 'reports' / run['id'] / 'report.html'
        report_file.unlink()
        download = client.get(f"/api/runs/{run['id']}/report?format=html&download=true")
        assert download.status_code == 200 and report_file.exists()


def test_paused_run_recovers_as_interrupted(tmp_path):
    app = create_app(tmp_path)
    target = Target.model_validate(demo_target())
    target.id = 'target'
    app.state.store.put('target', target.id, target.model_dump())
    run = app.state.workflow.create(RunRequest(target_id=target.id))
    run['status'] = 'paused'
    app.state.store.put('run', run['id'], run)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f"/api/runs/{run['id']}").json()['status'] == 'interrupted'


def test_demo_estimate_uses_rendered_requests_and_inputs():
    target = Target.model_validate(demo_target())
    estimated = estimate(target, 50, Limits(max_requests=11))
    assert estimated['requests'] == 11 and estimated['can_start']
    assert estimated['tokens'] > 11 * 1024


def test_generated_scope_exceeding_budget_is_blocked_before_dispatch():
    target = Target.model_validate(demo_target())
    limits = Limits(max_tokens=1200)
    case = single_case()
    case['turns'][0]['input'] = 'x' * 2000
    usage = Budget(limits).usage
    with pytest.raises(BudgetExceeded, match='remaining tokens'):
        enforce_generated_budget(target, [case], limits, usage)
    assert usage['requests'] == 0


def test_generator_cannot_invent_planning_objectives():
    target = demo_target()
    offline = OfflineGateway()
    plan, _ = offline.generate_json('', json.dumps({'target': target}), purpose='platform_plan')
    result, _ = offline.generate_json('', json.dumps({'target': target, 'plan': plan, 'test_count': 1, 'exploration': 50}), purpose='test_generator')
    result['cases'][0]['objective_id'] = 'invented-objective'
    mock = Mock()
    mock.generate_json.return_value = (result, {})
    with pytest.raises(ValueError, match='planning objective'):
        TestGeneratorAgent(mock).generate(target, plan, 1, 50)


def test_regression_matching_survives_new_case_ids():
    earlier = [{'test_id': 'old-id', 'regression_key': 'same-boundary', 'classification': 'FAIL'}]
    later = [{'test_id': 'new-id', 'regression_key': 'same-boundary', 'classification': 'PASS'}]
    assert compare_evaluations(earlier, later)['resolved'] == ['old-id']
    later[0]['classification'] = 'INCONCLUSIVE'
    assert compare_evaluations(earlier, later)['not_retested'] == ['old-id']


def test_equal_names_on_different_endpoints_are_not_shared_history(tmp_path):
    app = create_app(tmp_path)
    first = Target.model_validate(demo_target('http://127.0.0.1:8001/api/chat'))
    first.id = 'one'
    app.state.store.put('target', first.id, first.model_dump())
    run = app.state.workflow.create(RunRequest(target_id=first.id))
    run['status'] = 'completed'
    app.state.store.put('run', run['id'], run)
    second = demo_target('http://127.0.0.1:8002/api/chat')
    assert app.state.workflow.history(second) == []


async def test_http_conversation_identity_auth_and_nested_observations(monkeypatch):
    target = Target.model_validate(demo_target())
    target.adapter = Adapter(kind='http', endpoint=target.adapter.endpoint,
                             request_template={'messages': '{messages}', 'session': '{session}', 'principal': '{user}'},
                             response_path='result.text', tool_calls_path='result.tools', usage_path='metrics.usage',
                             auth_env_by_user={'tenant-a': 'AUDIT_A_KEY', 'tenant-b': 'AUDIT_B_KEY'})
    monkeypatch.setenv('AUDIT_A_KEY', 'synthetic-a-credential')
    monkeypatch.setenv('AUDIT_B_KEY', 'synthetic-b-credential')
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={'result': {'text': 'Secure reply', 'tools': []}, 'metrics': {'usage': {'total_tokens': 9}}})
    original = httpx.AsyncClient
    monkeypatch.setattr('agents.execution_agent.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    case = single_case()
    case['turns'] = [{'input': 'Private synthetic context', 'user': 'tenant-a'},
                     {'input': 'Follow up', 'user': 'tenant-a'}, {'input': 'New identity', 'user': 'tenant-b'}]
    limits = Limits(requests_per_second=50, price_per_million=1)
    result = await ExecutionAgent(target, limits, Budget(limits), asyncio.Event(), asyncio.Event()).execute(case)
    bodies = [json.loads(r.content) for r in requests]
    assert len(bodies[1]['messages']) == 3
    assert bodies[2]['messages'] == [{'role': 'user', 'content': 'New identity'}]
    assert len({body['session'] for body in bodies}) == 1
    assert requests[0].headers['authorization'] == 'Bearer synthetic-a-credential'
    assert requests[2].headers['authorization'] == 'Bearer synthetic-b-credential'
    assert all(t['tool_calls_available'] for t in result['turns'])


@pytest.mark.parametrize('status,classification', [(403, 'PASS'), (200, 'FAIL'), (503, 'ERROR')])
async def test_expected_access_denial_and_server_errors(monkeypatch, status, classification):
    def handle(request):
        return httpx.Response(status, json={'detail': 'Access denied'} if status == 403 else {'response': 'Synthetic reply'})
    original = httpx.AsyncClient
    monkeypatch.setattr('agents.execution_agent.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    target = Target.model_validate(demo_target())
    target.adapter.kind = 'http'
    case = single_case()
    case['assertions'] = [{'kind': 'http_status', 'value': 403}]
    limits = Limits(price_per_million=1)
    execution = await ExecutionAgent(target, limits, Budget(limits), asyncio.Event(), asyncio.Event()).execute(case)
    assert EvaluationAgent(OfflineGateway()).evaluate(case, execution)['classification'] == classification


def test_partial_multiturn_evidence_is_inconclusive():
    case = single_case()
    case['turns'] *= 2
    result = EvaluationAgent(OfflineGateway()).evaluate(case, {'turns': [{'outcome': 'OK', 'response': 'Safe first turn'}]})
    assert result['classification'] == 'INCONCLUSIVE'


def test_user_input_placeholders_are_preserved_literally():
    assert render('Question: {input}', {'input': '{session}', 'session': 'private-id'}) == 'Question: {session}'


@pytest.mark.parametrize('value', ['', 'not an environment name', 'inline-credential'])
def test_invalid_credential_references_rejected(value):
    with pytest.raises(ValueError):
        Adapter(auth_env_by_user={'tenant-a': value})


def test_server_failure_cannot_be_a_secure_denial_assertion():
    with pytest.raises(ValueError):
        Assertion(kind='http_status', value=503)


def test_openrouter_zero_quota_skips_retries(monkeypatch):
    monkeypatch.setattr(gateway_module, 'gemini_client', None)
    monkeypatch.setattr(gateway_module, 'OPENROUTER_API_KEY', 'synthetic-test-key')
    gateway = gateway_module.LLMGateway()
    gateway._openrouter_models = [{'id': 'zero'}, {'id': 'usable'}]
    failed = Mock(status_code=429, text='quota limit: 0')
    passed = Mock(status_code=200)
    passed.json.return_value = {'choices': [{'message': {'content': '{"ok":true}'}}], 'usage': {'total_tokens': 17}}
    post = Mock(side_effect=[failed, passed])
    monkeypatch.setattr(gateway_module.requests, 'post', post)
    usage = Mock()
    gateway.on_usage = usage
    result, metadata = gateway.generate_json('system', 'user')
    assert result['ok'] and post.call_count == 2
    assert metadata['fallback'] is True
    usage.assert_called_once_with(17)


def test_retry_is_distinct_from_model_fallback():
    gateway = gateway_module.LLMGateway()
    gateway._record('google', 'first', 'failed', 'plan', 'fingerprint', 1)
    gateway._record('google', 'first', 'success', 'plan', 'fingerprint', 2)
    assert gateway.history[-1]['fallback'] is False
    gateway._record('google', 'second', 'success', 'plan', 'fingerprint', 1)
    assert gateway.history[-1]['fallback'] is True
    gateway._record('google', 'second', 'success', 'evaluation', 'different-context', 1)
    assert gateway.history[-1]['fallback'] is False


def test_campushelp_rejects_foreign_host_without_internal_error():
    from examples.campushelp.app import app
    with TestClient(app) as client:
        assert client.get('/api/health', headers={'Host': 'foreign.invalid'}).status_code == 403


def test_identity_credentials_redacted_even_with_custom_variable_names(monkeypatch):
    monkeypatch.setenv('AUDIT_A_KEY', 'synthetic-account-a-secret')
    assert redact({'response': 'Echo: synthetic-account-a-secret'}) == {'response': 'Echo: [REDACTED]'}
    assert redact({'regression_key': 'public-regression-fingerprint'})['regression_key'] == 'public-regression-fingerprint'


def test_gateway_preferences_are_per_run(monkeypatch):
    monkeypatch.setattr(gateway_module, 'discover_gemini_models', lambda: ['first', 'second'])
    first = gateway_module.LLMGateway(preferred_model='first', only_free=True)
    second = gateway_module.LLMGateway(preferred_model='second', only_free=False)
    assert first._get_gemini_models()[0] == 'first'
    assert second._get_gemini_models()[0] == 'second'
    assert first.only_free and not second.only_free


@pytest.mark.parametrize('confidence', [None, 'not-a-number', float('nan'), 2])
def test_malformed_judge_confidence_cannot_create_findings(confidence):
    gateway = Mock()
    gateway.generate_json.return_value = ({'classification': 'FAIL', 'confidence': confidence, 'explanation': 'Unverified', 'evidence_quote': 'Safe'}, {})
    case = single_case()
    case['assertions'] = [{'kind': 'subjective'}]
    evidence = {'turns': [{'outcome': 'OK', 'response': 'Safe response'}]}
    assert EvaluationAgent(gateway).evaluate(case, evidence)['classification'] == 'INCONCLUSIVE'


def test_judge_outage_is_error_and_does_not_abort_the_run():
    gateway = Mock()
    gateway.generate_json.side_effect = RuntimeError('All providers exhausted')
    case = single_case()
    case['assertions'] = [{'kind': 'subjective'}]
    evidence = {'turns': [{'outcome': 'OK', 'response': 'Safe response'}]}
    assert EvaluationAgent(gateway).evaluate(case, evidence)['classification'] == 'ERROR'


def test_clarification_answers_are_validated():
    from agents.clarification_agent import ClarificationAgent
    with pytest.raises(ValueError, match='listed answer'):
        ClarificationAgent().apply(Target(), {'tools': 'Unexpected option'})
    with pytest.raises(ValueError, match='listed options'):
        ClarificationAgent().apply(Target(), {'data': 'not-a-checkbox-list'})


def test_live_workflow_uses_shared_gateway_and_real_target_http(tmp_path, campus_url, monkeypatch):
    from agents.planner_agent import PlannerAgent
    from services.scenarios import objectives
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-mocked-tavily-key')
    prepared = Mock(return_value={'research': [], 'mode': 'Mocked web research for integration test'})
    planned = Mock(return_value=({'summary': 'Mocked live planner output'}, {'provider': 'mock', 'model': 'mock-planner'}))
    monkeypatch.setattr(PlannerAgent, 'prepare_evidence', prepared)
    monkeypatch.setattr(PlannerAgent, 'create_plan', planned)
    instances = []
    class SharedMockGateway(OfflineGateway):
        def __init__(self, **kwargs):
            super().__init__()
            self.before_call = self.on_event = self.on_usage = None
            self.max_output_tokens = 1024
            instances.append(self)
        def generate_json(self, system, user, temperature=.2, purpose='platform_plan'):
            if self.before_call:
                self.before_call(system, user)
            result, metadata = super().generate_json(system, user, temperature, purpose)
            metadata.update(provider='mock-provider', model='mock-live-reasoning')
            return result, metadata
    monkeypatch.setattr(gateway_module, 'LLMGateway', SharedMockGateway)
    with TestClient(create_app(tmp_path)) as client:
        target = client.post('/api/targets', json=demo_target(campus_url)).json()
        request = {'target_id': target['id'], 'mode': 'live', 'exploration': 50,
                   'limits': {'price_per_million': 1, 'max_tokens': 200000, 'requests_per_second': 50}}
        created = client.post('/api/runs', json=request)
        assert created.status_code == 201, created.text
        id = created.json()['id']
        client.post('/api/runs/' + id + '/start')
        run = wait_run(client, id)
        assert run['status'] == 'completed', run['error']
        assert len(instances) == 1
        assert prepared.call_count == planned.call_count == 1
        assert run['report']['counts']['FAIL'] == 8
        assert run['usage']['target_requests'] == 11 and run['usage']['model_requests'] == 2
        assert run['plan']['original_plan']['summary'] == 'Mocked live planner output'
        assert all(e['turns'][0]['status'] == 200 for e in run['executions'])


def test_legacy_root_cli_reuses_research_and_saves_redacted_outputs(tmp_path, monkeypatch):
    import runpy
    import sys
    from pathlib import Path
    import orchestrator
    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-cli-research-key')
    monkeypatch.setenv('REFRESH_RESEARCH', 'false')
    planner = Mock()
    planner.prepare_evidence.return_value = {'research': [{'title': 'Synthetic reference'}], 'api_key': 'never-store-this'}
    planner.create_plan.return_value = ({'test_priorities': [], 'api_key': 'never-store-this'}, {'provider': 'mock', 'model': 'mock-planner'})
    monkeypatch.setattr(orchestrator, 'PlannerAgent', Mock(return_value=planner))
    monkeypatch.setattr(orchestrator, 'WebResearcher', Mock())
    monkeypatch.setattr(sys, 'argv', ['main.py', 'example.json'])
    runpy.run_path(str(root / 'main.py'), run_name='__main__')
    monkeypatch.setattr(sys, 'argv', ['main.py', 'example.json'])
    runpy.run_path(str(root / 'main.py'), run_name='__main__')
    assert planner.prepare_evidence.call_count == 1
    assert planner.create_plan.call_count == 2
    assert json.loads((tmp_path / 'outputs' / 'security_test_plan.json').read_text())['api_key'] == '[REDACTED]'
    assert (tmp_path / 'outputs' / 'planner_run_metadata.json').exists()
    assert (tmp_path / 'outputs' / 'llm_history.json').exists()
    checkpoint = next((tmp_path / 'outputs' / 'checkpoints').glob('*.json'))
    assert 'never-store-this' not in checkpoint.read_text()
