import asyncio
import json
import os
import time
import uuid
import httpx
from database.store import now
from services.security import enforce_scope, redact
from services.budget import BudgetExceeded
from services.http_contract import path_get, render, payload_for


class ExecutionAgent:
    def __init__(self, target, limits, budget, cancel, pause, on_reservation=None):
        self.target, self.limits, self.budget = target, limits, budget
        self.cancel, self.pause = cancel, pause
        self.rate_lock = asyncio.Lock()
        self.next_request = 0
        self.on_reservation = on_reservation

    async def checkpoint(self):
        while self.pause.is_set() and not self.cancel.is_set():
            self.budget.check_time()
            await asyncio.sleep(0.1)
        self.budget.check_time()
        if self.cancel.is_set():
            raise asyncio.CancelledError()

    async def execute(self, case):
        endpoint = enforce_scope(self.target)
        adapter = self.target.adapter
        evidence = []
        session = uuid.uuid4().hex
        async with httpx.AsyncClient(timeout=self.limits.timeout_seconds, follow_redirects=False, trust_env=False) as client:
            for repetition in range(case['repetitions']):
                session = uuid.uuid4().hex
                conversations = {}
                for turn in case['turns']:
                    await self.checkpoint()
                    async with self.rate_lock:
                        delay = self.next_request - time.monotonic()
                        if delay > 0:
                            await asyncio.sleep(delay)
                        self.next_request = time.monotonic() + 1 / self.limits.requests_per_second
                    await self.checkpoint()
                    remaining = self.limits.max_seconds - self.budget.usage['elapsed_seconds']
                    price = 0 if adapter.kind == 'campushelp' else (self.limits.price_per_million or 0)
                    messages = conversations.setdefault(turn['user'], [])
                    messages.append({'role': 'user', 'content': turn['input']})
                    payload = payload_for(adapter, turn, session, self.limits.max_output_tokens, messages)
                    self.budget.reserve(len(json.dumps(payload, ensure_ascii=False).encode()) + self.limits.max_output_tokens, price)
                    self.budget.usage['target_requests'] = self.budget.usage.get('target_requests', 0) + 1
                    if self.on_reservation:
                        self.on_reservation()
                    headers = dict(adapter.headers)
                    auth_env = adapter.auth_env_by_user.get(turn['user'], adapter.auth_env)
                    if adapter.auth_env_by_user and turn['user'] not in adapter.auth_env_by_user:
                        raise ValueError('No authorized authentication reference for identity ' + turn['user'])
                    if auth_env:
                        secret = os.getenv(auth_env)
                        if not secret:
                            raise ValueError(f'Target authentication variable {auth_env} is not configured.')
                        headers[adapter.auth_header] = adapter.auth_prefix + secret
                    start = time.monotonic()
                    item = {'input': turn['input'], 'user': turn['user'], 'session_id': session, 'timestamp': now(), 'repetition': repetition,
                            'status': None, 'response': '', 'tool_calls': [], 'outcome': 'ERROR', 'provider': self.target.llm.get('provider'), 'model': self.target.llm.get('model')}
                    try:
                        async with client.stream('POST', endpoint, json=payload, headers=headers, timeout=min(self.limits.timeout_seconds, max(0.1, remaining))) as response:
                            item['status'] = response.status_code
                            content = bytearray()
                            async for chunk in response.aiter_bytes():
                                content.extend(chunk)
                                if len(content) > adapter.max_response_bytes:
                                    raise ValueError('Target response exceeds configured byte limit.')
                            body = json.loads(content)
                            if not isinstance(body, dict):
                                raise ValueError('Target response must be a JSON object.')
                        item['body'] = body
                        def field(path, default=None):
                            try:
                                return path_get(body, path) if path else default
                            except (KeyError, IndexError, ValueError, TypeError):
                                return default
                        item['provider'] = field(adapter.provider_path, item['provider'])
                        item['model'] = field(adapter.model_path, item['model'])
                        expected_denial = any(a['kind'] == 'http_status' and a['value'] == response.status_code for a in case['assertions'])
                        if expected_denial and 400 <= response.status_code < 500:
                            item['response'] = str(field(adapter.response_path, body.get('detail', '')))
                        else:
                            item['response'] = str(path_get(body, adapter.response_path))
                        tool_calls = field(adapter.tool_calls_path)
                        item['tool_calls_available'] = isinstance(tool_calls, list)
                        item['tool_calls'] = tool_calls if isinstance(tool_calls, list) else []
                        usage = field(adapter.usage_path, {})
                        if not isinstance(usage, dict):
                            raise ValueError('Configured token usage field must be a JSON object.')
                        item['token_usage'] = usage
                        self.budget.usage['tokens_observed'] += int(usage.get('total_tokens', 0) or 0)
                        item['outcome'] = 'OK' if 200 <= response.status_code < 300 else 'ERROR'
                        if expected_denial and 400 <= response.status_code < 500:
                            item['outcome'] = 'DENIED'
                        messages.append({'role': 'assistant', 'content': item['response']})
                    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
                        item['error'] = str(error)
                    item['latency_ms'] = round((time.monotonic() - start) * 1000, 2)
                    evidence.append(redact(item))
        return {'test_id': case['id'], 'turns': evidence, 'completed_at': now()}
