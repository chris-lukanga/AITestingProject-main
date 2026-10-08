from schemas.contracts import Target


class ClarificationAgent:
    def questions(self, target: Target):
        scope = target.testing_scope
        questions = []
        def add(id, label, type='single', options=None, essential=False):
            questions.append(dict(id=id, label=label, type=type, options=options or [], essential=essential))
        if scope.get('authorized') is not True:
            add('authorized', 'Do you have permission to test this exact target?', options=['Yes', 'No'], essential=True)
        if not target.adapter.endpoint or target.adapter.endpoint not in scope.get('allowed_endpoints', []):
            add('endpoint', 'Enter the exact authorized chat endpoint, including its path.', 'short', essential=True)
        if not scope.get('environment'):
            add('environment', 'Which environment is this?', options=['Local development', 'Authorized staging', 'Production', 'Other', 'Unknown'])
        if 'tools_enabled' not in target.integration:
            add('tools', 'Does the target have access to external tools?', options=['Read-only', 'Can modify data', 'No', 'Unknown'])
        if not target.data_access:
            add('data', 'Which data can the target access?', 'multiple', ['Public documents', 'Synthetic private records', 'Other', 'Unknown'])
        if not target.application.get('purpose'):
            add('purpose', 'Describe the application purpose and any scope constraints.', 'long')
        return questions

    def apply(self, target, answers):
        known = {q['id']: q for q in self.questions(target)}
        # Keep recognized answers editable, including an explicit Unknown choice.
        definitions = {q['id']: q for q in self.questions(Target())}
        for id, answer in answers.items():
            question = known.get(id) or definitions.get(id)
            if question is None:
                raise ValueError('Unknown clarification field: ' + id)
            if question['type'] == 'single' and answer not in question['options']:
                raise ValueError('Choose a listed answer for ' + id)
            if question['type'] == 'multiple' and (not isinstance(answer, list) or any(value not in question['options'] for value in answer)):
                raise ValueError('Choose listed options for ' + id)
            if question['type'] in ('short', 'long') and (not isinstance(answer, str) or not answer.strip() or len(answer) > 8000):
                raise ValueError('Enter a nonempty text answer of at most 8000 characters for ' + id)
        target.clarification_answers.update(answers)
        if 'authorized' in answers:
            target.testing_scope['authorized'] = answers['authorized'] == 'Yes'
        if 'endpoint' in answers:
            from schemas.contracts import Adapter
            target.adapter = Adapter.model_validate(dict(target.adapter.model_dump(), endpoint=answers['endpoint']))
            target.testing_scope['allowed_endpoints'] = [target.adapter.endpoint]
        if 'environment' in answers:
            target.testing_scope['environment'] = answers['environment']
        if 'tools' in answers:
            target.integration.update(tools_enabled=None if answers['tools'] == 'Unknown' else answers['tools'] != 'No', tool_access=answers['tools'])
        if 'data' in answers:
            target.data_access = {'declared': answers['data']}
        if 'purpose' in answers:
            target.application['purpose'] = answers['purpose']
        return target
