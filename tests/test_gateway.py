import json
from types import SimpleNamespace as Obj
from unittest.mock import Mock
import pytest
import llm_gateway as g
from services.budget import BudgetExceeded


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(g, 'GEMINI_API_KEY', None)
    monkeypatch.setattr(g, 'OPENROUTER_API_KEY', None)
    monkeypatch.setattr(g, 'gemini_client', None)
    monkeypatch.setattr(g, 'backoff_sleep', lambda attempt: None)
    monkeypatch.setattr(g, 'GEMINI_MAX_RETRIES', 2)
    monkeypatch.setattr(g, 'OPENROUTER_MAX_RETRIES', 2)
    monkeypatch.setattr(g, 'GEMINI_CAPABILITIES', {})


def client(monkeypatch, side_effect):
    generate = Mock(side_effect=side_effect)
    monkeypatch.setattr(g, 'gemini_client', Obj(models=Obj(generate_content=generate)))
    gateway = g.LLMGateway()
    gateway._gemini_models = ['first', 'second']
    return gateway, generate


def test_discovery(monkeypatch):
    listed = [Obj(name='models/gemini-text', supported_actions=['generateContent'], input_token_limit=10000),
              Obj(name='models/gemini-image', supported_actions=['generateContent']),
              Obj(name='models/gemini-retired', supported_actions=['generateContent']),
              Obj(name='models/gemini-embed', supported_actions=['embedContent'])]
    monkeypatch.setattr(g, 'gemini_client', Obj(models=Obj(list=lambda: listed)))
    assert g.discover_gemini_models() == ['gemini-text']
    assert g.GEMINI_CAPABILITIES['gemini-text']['input_token_limit'] == 10000


@pytest.mark.parametrize('failure', ['404 NOT_FOUND', '429 RESOURCE_EXHAUSTED', '503 UNAVAILABLE', '429 quota limit: 0'])
def test_fallback_context_preserved(monkeypatch, failure):
    attempts = 1 if '404' in failure or 'limit: 0' in failure else 2
    gateway, generate = client(monkeypatch, [RuntimeError(failure)] * attempts + [Obj(text='{"ok":true}')])
    result, metadata = gateway.generate_json('Complete system context', 'Complete user context')
    assert result == {'ok': True}
    assert metadata['model'] == 'second'
    assert len({h['context_fingerprint'] for h in gateway.history}) == 1
    assert all(c.kwargs['contents'] == 'Complete user context' for c in generate.call_args_list)
    assert all(c.kwargs['config'].system_instruction == 'Complete system context' for c in generate.call_args_list)


def test_temporary_error_retries_same_model(monkeypatch):
    gateway, generate = client(monkeypatch, [RuntimeError('503 unavailable'), Obj(text='{"ok":true}')])
    _, meta = gateway.generate_json('system', 'user')
    assert meta['model'] == 'first' and generate.call_count == 2


def test_resource_exhausted_is_not_zero_quota():
    assert not g.is_zero_quota_error('429 RESOURCE_EXHAUSTED')
    assert g.is_zero_quota_error('429 quota limit: 0')


def test_openrouter_after_auth_failure(monkeypatch):
    gateway, generate = client(monkeypatch, [RuntimeError('401 INVALID_API_KEY')])
    monkeypatch.setattr(g, 'OPENROUTER_API_KEY', 'synthetic-test-token')
    gateway._openrouter_models = [{'id':'other:free','context_length':10000,'supports_response_format':True}]
    response = Mock(status_code=200)
    response.json.return_value = {'choices':[{'message':{'content':'{"answer":42}'}}], 'model':'other:free'}
    response.text = json.dumps(response.json.return_value)
    post = Mock(return_value=response)
    monkeypatch.setattr(g.requests, 'post', post)
    result, meta = gateway.generate_json('system', 'user')
    assert result == {'answer':42}, 'Must parse message content, not provider envelope.'
    assert meta['provider'] == 'openrouter' and generate.call_count == 1
    assert post.call_args.kwargs['json']['messages'] == [{'role':'system','content':'system'},{'role':'user','content':'user'}]


@pytest.mark.parametrize('status', [404, 429, 503])
def test_openrouter_model_fallback(monkeypatch, status):
    monkeypatch.setattr(g, 'OPENROUTER_API_KEY', 'synthetic-test-token')
    gateway = g.LLMGateway()
    gateway._openrouter_models = [{'id':x,'context_length':20000} for x in ['first','second']]
    failed = Mock(status_code=status, text=str(status))
    passed = Mock(status_code=200, text='unused')
    passed.json.return_value = {'choices':[{'message':{'content':'{"ok":true}'}}]}
    monkeypatch.setattr(g.requests, 'post', Mock(side_effect=[failed] * (1 if status == 404 else 2) + [passed]))
    result, meta = gateway.generate_json('system','user')
    assert result['ok'] and meta['model'] == 'second'


def test_free_discovery_and_context(monkeypatch):
    monkeypatch.setattr(g, 'OPENROUTER_API_KEY', 'synthetic-test-token')
    model = lambda id, output, price: {'id':id,'architecture':{'output_modalities':output,'input_modalities':['text']},'pricing':{'prompt':price,'completion':price},'context_length':20000,'supported_parameters':['response_format']}
    response=Mock()
    response.json.return_value={'data':[model('text:free',['text'],'0'),model('image:free',['image'],'0'),model('paid',['text'],'1')]}
    monkeypatch.setattr(g.requests, 'get', Mock(return_value=response))
    assert [m['id'] for m in g.discover_openrouter_free_models()] == ['text:free']
    gateway = g.LLMGateway()
    post = Mock()
    monkeypatch.setattr(g.requests, 'post', post)
    assert gateway._try_openrouter_model({'id':'short','context_length':10},'system','context',0,'fingerprint','test') == (None,False)
    post.assert_not_called()


@pytest.mark.parametrize('raw', ['', 'not JSON', '[1,2]'])
def test_json_rejects_invalid(raw):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        g.parse_json_response(raw)


def test_json_fences():
    assert g.parse_json_response('```json\n{"ok":true}\n```') == {'ok':True}


def test_json_invalid_fallback(monkeypatch):
    gateway,_ = client(monkeypatch,[Obj(text='broken'),Obj(text='broken'),Obj(text='{"ok":true}')])
    result, meta=gateway.generate_json('system','user')
    assert result['ok'] and meta['model']=='second'


def test_budget_hook_stops_fallback(monkeypatch):
    gateway, generate = client(monkeypatch,[Obj(text='{"ok":true}')])
    def stop(*args): raise BudgetExceeded('No requests remaining.')
    gateway.before_call=stop
    with pytest.raises(BudgetExceeded):gateway.generate_json('system','user')
    generate.assert_not_called()


def test_history_redacts(monkeypatch):
    monkeypatch.setenv('CUSTOM_API_KEY','synthetic-private-credential')
    gateway=g.LLMGateway()
    gateway._record('test','test','failed','test','fp',1,error='synthetic-private-credential')
    assert 'synthetic-private-credential' not in str(gateway.history)
