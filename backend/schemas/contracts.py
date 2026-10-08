from typing import Any, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Adapter(BaseModel):
    kind: Literal['campushelp', 'http'] = 'http'
    endpoint: str = ''
    request_template: dict[str, Any] = Field(default_factory=lambda: {'message': '{input}', 'session_id': '{session}', 'max_tokens': '{max_tokens}'})
    response_path: str = 'response'
    tool_calls_path: str = 'tool_calls'
    usage_path: str = 'usage'
    provider_path: str = 'provider'
    model_path: str = 'model'
    headers: dict[str, str] = Field(default_factory=dict)
    auth_env: str = ''
    auth_env_by_user: dict[str, str] = Field(default_factory=dict)
    auth_header: str = 'Authorization'
    auth_prefix: str = 'Bearer '
    mode: Literal['weak', 'hardened'] = 'weak'
    max_response_bytes: int = Field(default=65536, ge=1024, le=1048576)

    @field_validator('endpoint')
    @classmethod
    def endpoint_format(cls, value):
        if value:
            u = urlsplit(value)
            if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError('Use an HTTP(S) endpoint without credentials, query parameters or fragments.')
        return value

    @field_validator('headers')
    @classmethod
    def public_headers(cls, value):
        if any(k.lower() in ('authorization', 'cookie', 'host', 'proxy-authorization', 'x-api-key') for k in value):
            raise ValueError('Use auth_env for credentials. Host and cookie overrides are forbidden.')
        return value

    @field_validator('auth_env')
    @classmethod
    def environment_reference(cls, value):
        import re
        if value and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
            raise ValueError('Authentication must reference an environment variable name.')
        return value

    @field_validator('auth_env_by_user')
    @classmethod
    def identity_references(cls, value):
        for reference in value.values():
            if not reference:
                raise ValueError('Each identity requires a nonempty authentication variable name.')
            cls.environment_reference(reference)
        return value

    @field_validator('auth_header')
    @classmethod
    def credential_header(cls, value):
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]+', value) or value.lower() in ('host', 'content-length', 'transfer-encoding', 'connection'):
            raise ValueError('Choose a valid authentication header; transport overrides are forbidden.')
        return value


class Target(BaseModel):
    id: str = ''
    application: dict[str, Any] = Field(default_factory=dict)
    llm: dict[str, Any] = Field(default_factory=dict)
    integration: dict[str, Any] = Field(default_factory=dict)
    data_access: dict[str, Any] = Field(default_factory=dict)
    security_controls: dict[str, Any] = Field(default_factory=dict)
    previous_failures: list[dict[str, Any]] = Field(default_factory=list)
    known_components: dict[str, Any] = Field(default_factory=dict)
    testing_scope: dict[str, Any] = Field(default_factory=dict)
    adapter: Adapter = Field(default_factory=Adapter)
    clarification_answers: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def legacy_url(self):
        # Import old files without silently assuming their root URL is a chat endpoint.
        if not self.adapter.endpoint and self.testing_scope.get('target_url'):
            self.adapter = Adapter.model_validate(dict(self.adapter.model_dump(), endpoint=self.testing_scope['target_url']))
        return self


class Limits(BaseModel):
    max_tests: int = Field(default=10, ge=1, le=200)
    max_requests: int = Field(default=60, ge=1, le=1000)
    max_tokens: int = Field(default=100000, ge=100, le=10000000)
    budget_usd: float = Field(default=1, ge=0, le=1000)
    max_seconds: int = Field(default=120, ge=1, le=3600)
    concurrency: int = Field(default=2, ge=1, le=10)
    requests_per_second: float = Field(default=5, gt=0, le=50)
    timeout_seconds: float = Field(default=10, ge=0.1, le=120)
    max_output_tokens: int = Field(default=1024, ge=64, le=8192)
    # User supplied ceiling, never described as verified provider pricing.
    price_per_million: float | None = Field(default=None, ge=0, le=10000)


class RunRequest(BaseModel):
    target_id: str
    exploration: int = Field(default=50, ge=0, le=100)
    mode: Literal['offline', 'live'] = 'offline'
    limits: Limits = Field(default_factory=Limits)


class PlanningObjective(BaseModel):
    id: str = Field(min_length=1)
    component: str = Field(min_length=1)
    owasp: str
    testing_objective: str = Field(min_length=1)
    severity: Literal['critical', 'high', 'medium', 'low']
    priority: int = Field(ge=1, le=10)
    evidence: str | list[Any] | dict[str, Any]
    explanation: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)
    historical: bool = False
    risk_category: str = ''

    @field_validator('owasp')
    @classmethod
    def official_mapping(cls, value):
        from services.taxonomy import OWASP
        if value not in OWASP:
            raise ValueError('Use an official OWASP 2026 category identifier.')
        return value


class SecurityPlan(BaseModel):
    model_config = ConfigDict(extra='allow')
    objectives: list[PlanningObjective] = Field(min_length=1, max_length=200)
    trust_boundaries: list[Any] = Field(default_factory=list)
    untested_risks: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_objectives(self):
        if len({objective.id for objective in self.objectives}) != len(self.objectives):
            raise ValueError('Planning objective IDs must be unique.')
        return self


class Assertion(BaseModel):
    kind: Literal['absent', 'contains', 'no_tool', 'json_equals', 'http_status', 'subjective']
    value: Any = ''
    path: str = ''

    @model_validator(mode='after')
    def meaningful_assertion(self):
        if self.kind in ('absent', 'contains') and not str(self.value):
            raise ValueError('Marker assertions require a nonempty value.')
        if self.kind == 'http_status' and (not isinstance(self.value, int) or isinstance(self.value, bool) or not 200 <= self.value < 500):
            raise ValueError('Expected HTTP status must be an integer between 200 and 499; server errors remain ERROR.')
        return self


class Turn(BaseModel):
    input: str = Field(min_length=1, max_length=8000)
    user: str = Field(default='student-a', min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.@-]+$')


class TestCase(BaseModel):
    id: str
    objective_id: str
    regression_key: str = ''
    title: str
    component: str
    owasp: str
    risk: str
    turns: list[Turn] = Field(min_length=1, max_length=5)
    expected: str
    criteria: str
    assertions: list[Assertion] = Field(default_factory=list)
    severity: Literal['critical', 'high', 'medium', 'low'] = 'high'
    priority: int = Field(default=1, ge=1, le=10)
    estimated_tokens: int = Field(default=1200, ge=1)
    estimated_cost: float | None = None
    repetitions: int = Field(default=1, ge=1, le=5)
    strategy: Literal['exploration', 'exploitation'] = 'exploration'
    mitigation: str
