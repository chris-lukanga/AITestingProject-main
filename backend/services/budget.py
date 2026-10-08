import time
import threading
import json
from services.http_contract import payload_for


def target_estimate(target, cases, limits):
    requests = tokens = 0
    for case in cases:
        for _ in range(case['repetitions']):
            conversations = {}
            for turn in case['turns']:
                messages = conversations.setdefault(turn['user'], [])
                messages.append({'role': 'user', 'content': turn['input']})
                payload = payload_for(target.adapter, turn, 'x' * 32, limits.max_output_tokens, messages)
                tokens += len(json.dumps(payload, ensure_ascii=False).encode()) + limits.max_output_tokens
                requests += 1
                # Bound retained assistant content by the adapter's response byte limit.
                messages.append({'role': 'assistant', 'content': 'x' * target.adapter.max_response_bytes})
    price = 0 if target.adapter.kind == 'campushelp' else limits.price_per_million
    return {'requests': requests, 'tokens': tokens, 'cost_usd': None if price is None else tokens * price / 1e6}


def enforce_generated_budget(target, cases, limits, usage):
    projected = target_estimate(target, cases, limits)
    for key, cap, used in [('requests', limits.max_requests, usage['requests']),
                           ('tokens', limits.max_tokens, usage['tokens_reserved']),
                           ('cost_usd', limits.budget_usd, usage['cost_reserved_usd'])]:
        value = projected[key]
        if value is None or used + value > cap:
            raise BudgetExceeded(f'Generated cases exceed the remaining {key} budget. Adjust the limit explicitly before resuming.')
    return projected


class BudgetExceeded(RuntimeError):
    pass


def estimate(target, exploration, limits, mode='offline'):
    tests = min(limits.max_tests, (10 if target.adapter.kind == 'campushelp' else 6) + exploration // 20)
    requests = tests * (4 if exploration < 35 else 2) + (0 if mode == 'offline' else 8)
    tokens = requests * (1200 + limits.max_output_tokens) + (0 if mode == 'offline' else 30000)
    if mode == 'offline' and target.adapter.kind == 'campushelp':
        from services.scenarios import objectives, cases
        context = {'target': target.model_dump()}
        context.update(plan=objectives(context), test_count=tests, exploration=exploration)
        generated = cases(context)['cases']
        tests = len(generated)
        projected = target_estimate(target, generated, limits)
        requests, tokens = projected['requests'], projected['tokens']
    seconds = requests / limits.requests_per_second + tests * 0.2
    price = 0 if target.adapter.kind == 'campushelp' and mode == 'offline' else limits.price_per_million
    cost = None if price is None else tokens * price / 1e6
    violations = []
    for label, value, cap in [('requests', requests, limits.max_requests), ('tokens', tokens, limits.max_tokens), ('seconds', seconds, limits.max_seconds)]:
        if value > cap:
            violations.append(f'Estimated {label} {value:.0f} exceeds limit {cap}.')
    if cost is not None and cost > limits.budget_usd:
        violations.append('Estimated cost exceeds the monetary limit.')
    if cost is None:
        violations.append('Supply a conservative price ceiling before a metered run; monetary limits cannot be enforced without one.')
    return {'tests': tests, 'requests': requests, 'tokens': tokens, 'seconds': round(seconds, 1), 'cost_usd': cost,
            'pricing': 'Local mock: no provider charges' if price == 0 else 'Approximate, user supplied ceiling; not verified live pricing',
            'warnings': ['High exploration can increase unique prompts, tokens, calls and runtime.'] if exploration > 65 else [],
            'violations': violations, 'can_start': not violations}


class Budget:
    """Reserve before dispatch; conservative reservations survive failed attempts."""
    def __init__(self, limits, existing=None):
        self.limits = limits
        self.start = time.monotonic()
        self.lock = threading.Lock()
        self.usage = existing or {'requests': 0, 'tokens_reserved': 0, 'tokens_observed': 0, 'cost_reserved_usd': 0.0, 'elapsed_seconds': 0.0}
        self.previous_elapsed = self.usage.get('elapsed_seconds', 0)

    def reserve(self, tokens, price=0):
        with self.lock:
            self.check_time()
            cost = tokens * price / 1e6
            if self.usage['requests'] + 1 > self.limits.max_requests:
                raise BudgetExceeded('Request limit reached.')
            if self.usage['tokens_reserved'] + tokens > self.limits.max_tokens:
                raise BudgetExceeded('Token reservation limit reached.')
            if self.usage['cost_reserved_usd'] + cost > self.limits.budget_usd:
                raise BudgetExceeded('Monetary reservation limit reached.')
            self.usage['requests'] += 1
            self.usage['tokens_reserved'] += tokens
            self.usage['cost_reserved_usd'] = round(self.usage['cost_reserved_usd'] + cost, 8)

    def check_time(self):
        self.usage['elapsed_seconds'] = round(self.previous_elapsed + time.monotonic() - self.start, 3)
        if self.usage['elapsed_seconds'] >= self.limits.max_seconds:
            raise BudgetExceeded('Execution time limit reached.')
