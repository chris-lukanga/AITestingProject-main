class RecommendationAgent:
    def recommend(self, target, historical=None, limits=None):
        history = historical or []
        # The most recent completed run describes current risk; older resolved
        # findings remain in reports rather than permanently depressing exploration.
        failures = target.previous_failures + [f for r in history[:1] for f in r.get('evaluations', []) if f['classification'] == 'FAIL']
        contributions = [{'reason': 'Balanced baseline', 'points': 50}]
        def add(reason, value):
            contributions.append({'reason': reason, 'points': value})
        severe = sum(f.get('severity', '').lower() in ('critical', 'high') for f in failures)
        add('Known high/critical failures favor focused retesting', -min(30, severe * 8))
        add('No prior completed coverage', 20 if not history else 0)
        components = max(1, len(target.known_components))
        tested = {e['component'].lower() for r in history for e in r.get('evaluations', []) if e['classification'] in ('PASS', 'FAIL')}
        untested = len({c.lower() for c in target.known_components} - tested) if target.known_components else (0 if tested else 1)
        add('Components without prior coverage', min(15, untested * 3))
        unknown = sum(target.integration.get(key) in (None, 'Unknown') for key in ('rag_enabled', 'tools_enabled', 'conversation_memory'))
        add('Uncertain architecture', unknown * 5)
        identity = lambda llm: (llm.get('provider'), llm.get('model_version') or llm.get('model'))
        changed = bool(history and identity(history[0]['target']['llm']) != identity(target.llm))
        add('Underlying model changed', 15 if changed else 0)
        add('High-priority risks from known failures', -min(10, len(failures) * 2))
        if limits:
            add('Small monetary budget favors focused checks', -5 if limits.budget_usd < 0.25 else 0)
            add('Limited request quota', -5 if limits.max_requests < 20 else 0)
            add('Short execution window', -5 if limits.max_seconds < 30 else 0)
        exploration = max(0, min(100, sum(c['points'] for c in contributions)))
        return {'exploration': exploration, 'exploitation': 100 - exploration, 'contributions': contributions,
                'explanation': 'Retest observed failures first; explore untested boundaries. Clamped sum of the displayed contributions.'}
