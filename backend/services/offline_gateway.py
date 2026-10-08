import json
from services.scenarios import objectives, cases
from llm_gateway import create_context_fingerprint


class OfflineGateway:
    """Explicit deterministic mode, shared by agents, never masquerades as an LLM."""
    def __init__(self):
        self.history = []

    def generate_json(self, system_instruction, user_prompt, temperature=0.2, purpose='platform_plan'):
        context = json.loads(user_prompt)
        if purpose == 'platform_plan':
            result = objectives(context)
        elif purpose == 'test_generator':
            result = cases(context)
        elif purpose == 'evaluation':
            result = {'classification': 'INCONCLUSIVE', 'explanation': 'No deterministic assertion and no live judge configured.', 'confidence': 0.0}
        else:
            raise ValueError(f'Unsupported offline agent purpose: {purpose}')
        metadata = {'provider': 'local', 'model': 'deterministic-rules-v1', 'purpose': purpose,
                    'context_fingerprint': create_context_fingerprint(system_instruction, user_prompt), 'fallback': False}
        self.history.append(dict(metadata, status='success'))
        return result, metadata
