"""Conservative regression matching, independent of generated case identifiers."""
import hashlib
import json


def same_target(first, second):
    return (first['application'].get('name'), first['adapter']['endpoint']) == (second['application'].get('name'), second['adapter']['endpoint'])


def regression_key(case):
    signature = {
        'title': ' '.join(case['title'].lower().split()),
        'component': case['component'].lower(),
        'owasp': case['owasp'],
        'assertions': case.get('assertions', []),
    }
    return hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:24]


def match_key(evaluation):
    # Legacy records still match their original deterministic IDs.
    return evaluation.get('regression_key') or evaluation['test_id']


def compare_evaluations(earlier, later):
    old = {match_key(e): e for e in earlier if e['classification'] == 'FAIL'}
    failed = {match_key(e): e for e in later if e['classification'] == 'FAIL'}
    passed = {match_key(e): e for e in later if e['classification'] == 'PASS'}
    return {
        'repeated': sorted(e['test_id'] for key, e in failed.items() if key in old),
        'new': sorted(e['test_id'] for key, e in failed.items() if key not in old),
        'resolved': sorted(e['test_id'] for key, e in old.items() if key in passed and key not in failed),
        'not_retested': sorted(e['test_id'] for key, e in old.items() if key not in passed and key not in failed),
    }
