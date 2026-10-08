"""Shared request rendering for execution and budget preflight."""
import re


def path_get(value, path):
    for part in path.split('.') if path else []:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def render(value, replacements):
    if isinstance(value, dict):
        return {key: render(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, replacements) for item in value]
    if isinstance(value, str):
        for key, replacement in replacements.items():
            if value == '{' + key + '}':
                return replacement
        # Substitute once so literal placeholders in test inputs stay literal.
        return re.sub(r'\{([a-z_]+)\}', lambda match: str(replacements.get(match[1], match[0])), value)
    return value


def payload_for(adapter, turn, session, max_tokens, messages):
    if adapter.kind == 'campushelp':
        return {'message': turn['input'], 'session_id': session, 'user': turn['user'], 'mode': adapter.mode, 'max_tokens': max_tokens}
    return render(adapter.request_template, {'input': turn['input'], 'session': session, 'user': turn['user'],
                                            'mode': adapter.mode, 'max_tokens': max_tokens, 'messages': messages})
