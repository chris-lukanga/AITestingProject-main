"""Allocate indivisible test cases by planned request budget, with explicit rounding."""


def allocate(cases, exploration):
    total = sum(len(c['turns']) * c['repetitions'] for c in cases)
    desired = total * exploration / 100
    # Subset-sum: favor later, less established objectives for exploration.
    subsets = {0: []}
    for index in reversed(range(len(cases))):
        weight = len(cases[index]['turns']) * cases[index]['repetitions']
        for amount, subset in list(subsets.items()):
            subsets.setdefault(amount + weight, subset + [index])
    actual = min(subsets, key=lambda n: (abs(n - desired), n))
    exploratory = set(subsets[actual])
    for index, case in enumerate(cases):
        case['strategy'] = 'exploration' if index in exploratory else 'exploitation'
    return {'requested_exploration': exploration, 'planned_exploration': round(actual / max(1, total) * 100, 1),
            'planned_exploitation': round((total - actual) / max(1, total) * 100, 1),
            'exploration_requests': actual, 'exploitation_requests': total - actual,
            'explanation': 'Request budget allocation, rounded to complete multi-turn cases. Platform planning overhead is shared.'}
