import html
import json
from collections import Counter
from agents.recommendation_agent import RecommendationAgent
from schemas.contracts import Target, Limits
from services.taxonomy import OWASP
from services.history import compare_evaluations, match_key


class ReportAgent:
    def build(self, run, previous=None):
        previous = previous or []
        evaluations = list(run['evaluations'])
        evaluated = {e['test_id'] for e in evaluations}
        for case in run['cases']:
            if case['id'] not in evaluated:
                evaluations.append({'test_id': case['id'], 'title': case['title'], 'component': case['component'], 'owasp': case['owasp'],
                                    'classification': 'SKIPPED', 'reason': 'Execution or evaluation was not completed before the run stopped.',
                                    'severity': case['severity'], 'confidence': 1.0, 'expected': case['expected'], 'observed': '',
                                    'evidence': {'turns': []}, 'mitigation': case['mitigation'], 'strategy': case['strategy']})
        outcomes = Counter(e['classification'] for e in evaluations)
        failures = [dict(e) for e in run['evaluations'] if e['classification'] == 'FAIL']
        earlier = previous[0].get('evaluations', []) if previous else []
        comparisons = compare_evaluations(earlier, run['evaluations'])
        old = {match_key(e) for e in earlier if e['classification'] == 'FAIL'}
        for f in failures:
            f['repeated'] = match_key(f) in old
            f['plain_description'] = f"The {f['component']} boundary did not meet the expected protection in this test."
            f['consequence'] = 'Unauthorized disclosure or unintended application behavior within the tested scope.'
        severities = Counter(f['severity'] for f in failures)
        recommendation = RecommendationAgent().recommend(Target.model_validate(run['target']), [run] + previous, Limits.model_validate(run['config']['limits']))
        coverage = sorted({e['owasp'] for e in run['evaluations'] if e['classification'] in ('PASS', 'FAIL')})
        reliability = Counter(t['outcome'] for e in run['executions'] for t in e['turns'])
        risk = next((s for s in ['critical', 'high', 'medium', 'low'] if severities[s]), 'No failure observed')
        if not outcomes['PASS'] and not outcomes['FAIL']:
            risk = 'Insufficient conclusive evidence'
        priority_components = list(dict.fromkeys(f['component'] for f in sorted(failures, key=lambda f: ['critical', 'high', 'medium', 'low'].index(f['severity']))))
        advice = f"Next run: {recommendation['exploration']}% exploration and {recommendation['exploitation']}% focused retesting. "
        advice += ('Validate fixes to ' + ', '.join(priority_components[:3]) + ' first. ') if failures else 'No failed boundary was observed; preserve these regression checks and explore uncovered components. '
        if comparisons['not_retested']:
            advice += f"Retest {len(comparisons['not_retested'])} prior failed checks without a conclusive current result. "
        if outcomes['INCONCLUSIVE']:
            advice += 'Add target-specific assertions or a live judge for inconclusive checks. '
        if run['status'] == 'limited':
            advice += 'Reduce the number of cases or explicitly adjust the exhausted limit before resuming. '
        usage = run['usage'] or {'requests': 0, 'tokens_reserved': 0, 'tokens_observed': 0, 'cost_reserved_usd': 0, 'elapsed_seconds': 0}
        return {'run_id': run['id'], 'target': run['target']['application'].get('name', 'Unnamed target'), 'status': run['status'],
                'assessment': risk, 'counts': {s: outcomes[s] for s in ['PASS', 'FAIL', 'INCONCLUSIVE', 'ERROR', 'SKIPPED']},
                'tests_executed': len(run['executions']), 'tests_planned': len(run['cases']), 'severity_counts': dict(severities),
                'findings': failures, 'evaluations': evaluations, 'coverage': coverage,
                'uncovered_categories': {k: v for k, v in OWASP.items() if k not in coverage},
                'exposed_components': dict(Counter(f['component'] for f in failures)),
                'new_failures': comparisons['new'], 'repeated_failures': comparisons['repeated'], 'resolved_failures': comparisons['resolved'],
                'not_retested_failures': comparisons['not_retested'],
                'provider_reliability': dict(reliability), 'providers': run.get('provider_history', []),
                'usage': usage, 'estimate': run['estimate'], 'strategy': run['config']['exploration'],
                'evidence_mode': run['config']['mode'],
                'allocation': run.get('allocation'),
                'strategy_outcomes': {s: dict(Counter(e['classification'] for e in run['evaluations'] if e['strategy'] == s)) for s in ['exploration', 'exploitation']},
                'next_run': recommendation, 'next_run_advice': advice.strip(),
                'limitations': ['A passing probe is not proof of security.',
                                'Offline mode uses deterministic rules and bundled references, not live AI.' if run['config']['mode'] == 'offline' else 'Live model judgments and retrieved web research require analyst review.',
                                'Token reservations are conservative estimates; target usage is observed only when reported.',
                                'Synthetic demo probes do not measure real model vulnerability rates. Supply-chain and poisoning risks need separate review.',
                                'The inert markup probe checks a declared plain-text contract; it does not demonstrate executable XSS.']}

    def html(self, report, product_name='LLM Integrity Lab'):
        esc = html.escape
        rows = ''.join(f"<tr><td>{esc(f['title'])}<br>{esc(f['owasp'])}</td><td>{esc(f['severity'])}<br>Confidence {f['confidence']}</td><td>{esc(f['component'])}</td><td>{esc(f['observed'])}<details><summary>Expected behavior & evidence</summary><p>{esc(f['expected'])}</p><p>{esc(f['reason'])}</p><pre>{esc(json.dumps(f['evidence'], indent=2))}</pre></details></td><td>{esc(f['mitigation'])}</td></tr>" for f in report['findings'])
        outcomes = ''.join(f"<tr><td>{esc(e['title'])}</td><td>{esc(e['classification'])}</td><td>{esc(e['component'])}</td><td>{esc(e['reason'])}</td></tr>" for e in report['evaluations'])
        return f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>{esc(product_name)} report</title>
        <style>body{{font:15px system-ui;margin:40px;color:#17232a}}table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;border:1px solid #ccd3d5;text-align:left}}pre{{white-space:pre-wrap}}h1{{color:#176660}}</style>
        <h1>{esc(product_name)}</h1><h2>{esc(report['target'])}</h2><p>Run {esc(report['run_id'])} · {esc(report['status'])} · {esc(report['assessment'])}</p>
        <p>{esc(str(report['counts']))} · {report['tests_executed']} executed</p>
        <table><thead><tr><th>Finding</th><th>Severity</th><th>Component</th><th>Observed evidence</th><th>Remediation</th></tr></thead><tbody>{rows}</tbody></table>
        <h2>Next run</h2><p>{report['next_run']['exploration']}% exploration / {report['next_run']['exploitation']}% focused retesting</p>
        <p>{esc(report['next_run_advice'])}</p><h2>Resource usage</h2><pre>{esc(json.dumps(report['usage'], indent=2))}</pre>
        <h2>All outcomes</h2><table><thead><tr><th>Test</th><th>Outcome</th><th>Component</th><th>Reason</th></tr></thead><tbody>{outcomes}</tbody></table>
        <h2>OWASP coverage</h2><p>{esc(', '.join(report['coverage']))}</p><p>Uncovered: {esc(', '.join(report['uncovered_categories']))}</p>
        <h2>Reliability & history</h2><pre>{esc(json.dumps({k: report[k] for k in ['provider_reliability','new_failures','repeated_failures','resolved_failures','strategy_outcomes','allocation']}, indent=2))}</pre>
        <h2>Limitations</h2><ul>{''.join('<li>'+esc(l)+'</li>' for l in report['limitations'])}</ul></html>'''
