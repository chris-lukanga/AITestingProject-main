import os
import json
import time
import random
import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from dotenv import load_dotenv
from google import genai
from google.genai import types
from services.security import redact


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# This is only the preferred model.
# If it no longer exists, the gateway automatically continues.
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

GEMINI_MAX_RETRIES = int(
    os.getenv(
        "GEMINI_MAX_RETRIES",
        "3"
    )
)

OPENROUTER_MAX_RETRIES = int(
    os.getenv(
        "OPENROUTER_MAX_RETRIES",
        "2"
    )
)

OPENROUTER_ONLY_FREE = (
    os.getenv(
        "OPENROUTER_ONLY_FREE",
        "true"
    ).lower()
    == "true"
)


# ============================================================
# CLIENT
# ============================================================

gemini_client = None
GEMINI_CAPABILITIES = {}

if GEMINI_API_KEY:
    gemini_client = genai.Client(
        api_key=GEMINI_API_KEY
    )


# ============================================================
# JSON HANDLING
# ============================================================

def parse_json_response(
    text: str
) -> Dict[str, Any]:

    if not text:
        raise ValueError(
            "Model returned an empty response."
        )

    text = text.strip()

    # Remove markdown JSON fences if present
    if text.startswith("```json"):
        text = text[7:]

    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError('Expected a JSON object from the model.')
    return result


# ============================================================
# CONTEXT FINGERPRINT
# ============================================================

def create_context_fingerprint(
    system_instruction: str,
    user_prompt: str
) -> str:

    """
    This lets us verify that every fallback model receives
    exactly the same planner context.
    """

    combined = (
        system_instruction
        + "\n\n=== USER PROMPT ===\n\n"
        + user_prompt
    )

    return hashlib.sha256(
        combined.encode("utf-8")
    ).hexdigest()[:16]


# ============================================================
# BACKOFF
# ============================================================

def backoff_sleep(
    attempt: int
):

    delay = min(
        2 ** attempt,
        12
    )

    delay += random.uniform(
        0,
        1
    )

    print(
        f"[GATEWAY] Waiting {delay:.1f}s before retry..."
    )

    time.sleep(delay)


# ============================================================
# ERROR CLASSIFICATION
# ============================================================

def is_auth_error(
    text: str
) -> bool:

    text = text.upper()

    markers = [
        "401",
        "403",
        "UNAUTHENTICATED",
        "INVALID API KEY",
        "INVALID_API_KEY"
    ]

    return any(
        marker in text
        for marker in markers
    )


def is_transient_error(
    text: str
) -> bool:

    text = text.upper()

    markers = [
        "408",
        "429",
        "500",
        "502",
        "503",
        "504",
        "UNAVAILABLE",
        "RESOURCE_EXHAUSTED",
        "RATE LIMIT",
        "RATE_LIMIT",
        "TIMEOUT",
        "TIMED OUT",
        "CONNECTION RESET",
        "CONNECTION ERROR"
    ]

    return any(
        marker in text
        for marker in markers
    )


def is_model_unavailable_error(
    text: str
) -> bool:

    text = text.upper()

    markers = [
        "404",
        "NOT_FOUND",
        "NO ENDPOINTS FOUND",
        "MODEL NOT FOUND",
        "NO AVAILABLE PROVIDER"
    ]

    return any(
        marker in text
        for marker in markers
    )


def is_zero_quota_error(
    text: str
) -> bool:

    text = text.upper()

    markers = [
        "ZERO QUOTA",
        "QUOTA LIMIT: 0",
        "LIMIT: 0",
    ]

    return any(
        marker in text
        for marker in markers
    )


def get_error_code(
    error: Exception
) -> Optional[str]:

    match = re.search(
        r"\b([4-5]\d{2})\b",
        str(error)
    )

    return match.group(1) if match else None


# ============================================================
# GEMINI MODEL DISCOVERY
# ============================================================

def discover_gemini_models() -> List[str]:

    if not gemini_client:

        return []


    print()
    print(
        "[DISCOVERY] Discovering Gemini text-generation models..."
    )


    discovered = []


    # Models we don't want acting as planner LLMs
    excluded_markers = [

        "image",
        "imagen",

        "veo",

        "embedding",
        "embed",

        "tts",
        "speech",

        "audio",

        "live",

        "robotics"
    ]


    try:

        for model in gemini_client.models.list():

            name = getattr(
                model,
                "name",
                ""
            )

            supported_actions = getattr(
                model,
                "supported_actions",
                []
            ) or []


            if not name:
                continue


            # Must support text generation API
            if (
                "generateContent"
                not in supported_actions
            ):

                continue


            if name.startswith(
                "models/"
            ):

                name = name.split(
                    "/",
                    1
                )[1]


            normalized = (
                name.lower()
            )
            if getattr(model, 'deprecated', False) or 'retired' in normalized:
                continue
            GEMINI_CAPABILITIES[name] = {
                'input_token_limit': getattr(model, 'input_token_limit', None),
                'output_token_limit': getattr(model, 'output_token_limit', None),
            }


            # ----------------------------------------
            # Only interested in Gemini LLMs
            # ----------------------------------------

            if "gemini" not in normalized:

                continue


            # ----------------------------------------
            # Exclude media-specific models
            # ----------------------------------------

            if any(
                marker in normalized
                for marker in excluded_markers
            ):

                continue


            if name not in discovered:

                discovered.append(
                    name
                )


    except Exception as error:

        print(
            "[DISCOVERY] Gemini discovery failed:"
        )

        print(
            redact(str(error))
        )

        return []


    # ========================================================
    # PRIORITY
    # ========================================================

    def priority(
        model_name: str
    ):

        name = model_name.lower()

        score = 100


        # Prefer Flash models for speed/cost
        if "flash" in name:
            score -= 30


        # Prefer stable releases
        if "preview" in name:
            score += 20

        if "experimental" in name:
            score += 30

        if "-exp" in name:
            score += 30


        return (
            score,
            model_name
        )


    discovered.sort(
        key=priority
    )


    print(
        f"[DISCOVERY] Found "
        f"{len(discovered)} eligible Gemini candidates; quota is unverified."
    )


    return discovered


# ============================================================
# OPENROUTER FREE MODEL DISCOVERY
# ============================================================

def _is_zero_price(
    value: Any
) -> bool:

    try:
        return float(value) == 0.0

    except (TypeError, ValueError):
        return False


def discover_openrouter_free_models(only_free=None) -> List[Dict[str, Any]]:

    if not OPENROUTER_API_KEY:
        return []

    print()
    print(
        "[DISCOVERY] Discovering OpenRouter free models..."
    )

    url = (
        "https://openrouter.ai/api/v1/models"
    )

    headers = {
        "Authorization":
            f"Bearer {OPENROUTER_API_KEY}"
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        body = response.json()

    except Exception as error:

        print(
            "[DISCOVERY] OpenRouter model discovery failed:"
        )

        print(
            f"            {redact(str(error))}"
        )

        return []


    candidates = []


    for model in body.get(
        "data",
        []
    ):

        model_id = model.get(
            "id"
        )

        if not model_id:
            continue


        # ----------------------------------------------------
        # Require text output when architecture metadata exists
        # ----------------------------------------------------

        architecture = model.get(
            "architecture",
            {}
        ) or {}

        output_modalities = architecture.get(
            "output_modalities",
            []
        ) or []

        input_modalities = architecture.get(
            "input_modalities",
            []
        ) or []


        if (
            output_modalities
            and "text" not in output_modalities
        ):
            continue


        if (
            input_modalities
            and "text" not in input_modalities
        ):
            continue


        # ----------------------------------------------------
        # Determine whether it is free
        # ----------------------------------------------------

        pricing = model.get(
            "pricing",
            {}
        ) or {}

        prompt_price = pricing.get(
            "prompt"
        )

        completion_price = pricing.get(
            "completion"
        )


        free_by_name = (
            model_id.endswith(":free")
        )

        free_by_price = (
            _is_zero_price(prompt_price)
            and
            _is_zero_price(completion_price)
        )


        if OPENROUTER_ONLY_FREE if only_free is None else only_free:

            if not (
                free_by_name
                or free_by_price
            ):
                continue


        supported_parameters = model.get(
            "supported_parameters",
            []
        ) or []


        supports_response_format = (
            "response_format"
            in supported_parameters
        )


        candidates.append({
            "id":
                model_id,

            "context_length":
                model.get(
                    "context_length",
                    0
                ) or 0,

            "supports_response_format":
                supports_response_format
        })


    # --------------------------------------------------------
    # Prefer structured-output models and larger contexts
    # --------------------------------------------------------

    candidates.sort(

        key=lambda model: (

            not model[
                "supports_response_format"
            ],

            -model[
                "context_length"
            ]
        )
    )


    print(
        f"[DISCOVERY] Found {len(candidates)} "
        f"eligible OpenRouter free text models."
    )


    return candidates


# ============================================================
# GATEWAY
# ============================================================

class LLMGateway:

    def __init__(self, preferred_model=None, only_free=None):

        self.history = []
        self.preferred_model = GEMINI_MODEL if preferred_model is None else preferred_model
        self.only_free = OPENROUTER_ONLY_FREE if only_free is None else only_free
        self.before_call = None
        self.on_usage = None
        self.on_event = None
        self.max_output_tokens = 4096
        self.timeout_seconds = 30

        self._gemini_models = None

        self._openrouter_models = None


    # ========================================================
    # HISTORY
    # ========================================================

    def _record(
        self,
        provider: str,
        model: str,
        status: str,
        purpose: str,
        fingerprint: str,
        attempt: int,
        error: Optional[str] = None,
        actual_model: Optional[str] = None
    ):

        entry = {

            "timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "provider":
                provider,

            "model":
                model,

            "actual_model":
                actual_model,

            "status":
                status,

            "purpose":
                purpose,

            "attempt":
                attempt,

            "context_fingerprint":
                fingerprint
        }
        related = [h for h in self.history if h['context_fingerprint'] == fingerprint]
        entry['fallback'] = any((h['provider'], h['model']) != (provider, model) for h in related)

        if error:
            entry["error"] = redact(error)

        self.history.append(entry)
        if self.on_event:
            self.on_event(entry)


    # ========================================================
    # BUILD GEMINI CANDIDATE LIST
    # ========================================================

    def _get_gemini_models(
        self
    ) -> List[str]:

        if self._gemini_models is not None:
            return self._gemini_models


        discovered = discover_gemini_models()


        models = []


        # --------------------------------------------
        # Always try preferred model first
        # even if it has become stale.
        # --------------------------------------------

        if self.preferred_model and (not discovered or self.preferred_model in discovered):
            models.append(
                self.preferred_model
            )


        # Then every model actually reported by Google
        models.extend(
            discovered
        )


        # Deduplicate preserving order
        models = list(
            dict.fromkeys(
                models
            )
        )


        self._gemini_models = models


        return models


    # ========================================================
    # BUILD OPENROUTER CANDIDATE LIST
    # ========================================================

    def _get_openrouter_models(
        self
    ) -> List[Dict[str, Any]]:

        if self._openrouter_models is not None:
            return self._openrouter_models


        models = []


        # --------------------------------------------
        # First try OpenRouter's free-model router.
        #
        # It automatically chooses a compatible model.
        # --------------------------------------------

        models.append({
            "id":
                "openrouter/free",

            "context_length":
                0,

            "supports_response_format":
                False
        })


        # --------------------------------------------
        # Then enumerate every currently free model.
        # --------------------------------------------

        discovered = (
            discover_openrouter_free_models(only_free=self.only_free)
        )


        seen = {
            "openrouter/free"
        }


        for model in discovered:

            model_id = model["id"]

            if model_id in seen:
                continue

            seen.add(
                model_id
            )

            models.append(
                model
            )


        self._openrouter_models = models


        return models


    # ========================================================
    # PUBLIC CALL
    # ========================================================

    def generate_json(
        self,
        system_instruction: str,
        user_prompt: str,
        temperature: float = 0.2,
        purpose: str = "planner"
    ) -> Tuple[
        Dict[str, Any],
        Dict[str, Any]
    ]:

        fingerprint = (
            create_context_fingerprint(
                system_instruction,
                user_prompt
            )
        )


        print()
        print(
            "=============================================="
        )
        print(
            "LLM GATEWAY"
        )
        print(
            "=============================================="
        )

        print(
            f"Purpose: {purpose}"
        )

        print(
            f"Context fingerprint: {fingerprint}"
        )

        print(
            "[GATEWAY] Full context will be preserved "
            "for every model."
        )


        total_models_tried = 0


        # ====================================================
        # PHASE 1 â€” GEMINI
        # ====================================================

        if gemini_client:

            gemini_models = (
                self._get_gemini_models()
            )


            print()
            print(
                f"[GATEWAY] Gemini candidates: "
                f"{len(gemini_models)}"
            )


            provider_auth_failed = False


            for index, model in enumerate(
                gemini_models,
                start=1
            ):

                if provider_auth_failed:
                    break


                total_models_tried += 1


                print()
                print(
                    f"[GATEWAY] Gemini "
                    f"{index}/{len(gemini_models)} "
                    f"â†’ {model}"
                )


                result, fatal_auth = (
                    self._try_gemini_model(

                        model=model,

                        system_instruction=(
                            system_instruction
                        ),

                        user_prompt=(
                            user_prompt
                        ),

                        temperature=(
                            temperature
                        ),

                        fingerprint=(
                            fingerprint
                        ),

                        purpose=purpose
                    )
                )


                if fatal_auth:

                    provider_auth_failed = True

                    print(
                        "[GATEWAY] Gemini credentials "
                        "cannot be used."
                    )

                    print(
                        "[GATEWAY] Skipping remaining "
                        "Gemini models."
                    )

                    break


                if result is not None:
                    return result


        else:

            print(
                "[GATEWAY] No Gemini API key. "
                "Skipping Gemini."
            )


        # ====================================================
        # PHASE 2 â€” OPENROUTER
        # ====================================================

        if OPENROUTER_API_KEY:

            print()
            print(
                "[GATEWAY] Gemini exhausted."
            )

            print(
                "[GATEWAY] Switching to OpenRouter."
            )


            openrouter_models = (
                self._get_openrouter_models()
            )


            print(
                f"[GATEWAY] OpenRouter candidates: "
                f"{len(openrouter_models)}"
            )


            provider_auth_failed = False


            for index, model_info in enumerate(
                openrouter_models,
                start=1
            ):

                if provider_auth_failed:
                    break


                model_id = (
                    model_info["id"]
                )


                total_models_tried += 1


                print()
                print(
                    f"[GATEWAY] OpenRouter "
                    f"{index}/{len(openrouter_models)} "
                    f"â†’ {model_id}"
                )


                result, fatal_auth = (
                    self._try_openrouter_model(

                        model_info=(
                            model_info
                        ),

                        system_instruction=(
                            system_instruction
                        ),

                        user_prompt=(
                            user_prompt
                        ),

                        temperature=(
                            temperature
                        ),

                        fingerprint=(
                            fingerprint
                        ),

                        purpose=purpose
                    )
                )


                if fatal_auth:

                    provider_auth_failed = True

                    print(
                        "[GATEWAY] OpenRouter credentials "
                        "cannot be used."
                    )

                    break


                if result is not None:
                    return result


        else:

            print()
            print(
                "[GATEWAY] OPENROUTER_API_KEY "
                "was not found."
            )


        # ====================================================
        # EVERY CANDIDATE FAILED
        # ====================================================

        # The orchestrator persists run-specific history even on failure.


        raise RuntimeError(

            f"All LLM candidates were exhausted. "
            f"{total_models_tried} model candidates "
            f"were attempted. "
            f"Context fingerprint: {fingerprint}"
        )


    # ========================================================
    # GEMINI MODEL CALL
    # ========================================================

    def _try_gemini_model(
    self,
    model: str,
    system_instruction: str,
    user_prompt: str,
    temperature: float,
    fingerprint: str,
    purpose: str
):
        capacity = GEMINI_CAPABILITIES.get(model, {})
        required = len((system_instruction + user_prompt).encode())
        if (capacity.get('input_token_limit') and required > capacity['input_token_limit']) or (capacity.get('output_token_limit') and self.max_output_tokens > capacity['output_token_limit']):
            self._record('google', model, 'skipped', purpose, fingerprint, 0, error='Insufficient input/output capacity')
            return None, False

        for attempt in range(
            1,
            GEMINI_MAX_RETRIES + 1
        ):

            if self.before_call:
                self.before_call(system_instruction, user_prompt)
            try:

                if gemini_client is None:
                    raise RuntimeError(
                        "Gemini client is not configured"
                    )

                response = (
                    gemini_client.models.generate_content(

                        model=model,

                        contents=user_prompt,

                        config=types.GenerateContentConfig(
                            max_output_tokens=self.max_output_tokens,
                            http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000)),

                            system_instruction=(
                                system_instruction
                            ),

                            temperature=(
                                temperature
                            ),

                            response_mime_type=(
                                "application/json"
                            )
                        )
                    )
                )


                response_text = response.text
                usage = getattr(response, 'usage_metadata', None)
                if self.on_usage and usage is not None:
                    self.on_usage(int(getattr(usage, 'total_token_count', 0) or 0))
                if response_text is None:
                    raise ValueError(
                        "Gemini returned no response text"
                    )

                result = parse_json_response(
                    response_text
                )


                metadata = {

                    "provider":
                        "google",

                    "model":
                        model,

                    "attempt":
                        attempt,

                    "purpose":
                        purpose,

                    "context_fingerprint":
                        fingerprint
                }


                self._record(

                    provider="google",

                    model=model,

                    status="success",

                    purpose=purpose,

                    fingerprint=fingerprint,

                    attempt=attempt
                )
                metadata['fallback'] = self.history[-1]['fallback']


                print(
                    f"[GATEWAY] SUCCESS â†’ "
                    f"Google / {model}"
                )


                return (
                    (
                        result,
                        metadata
                    ),
                    False
                )


            except Exception as error:

                error_text = redact(str(error))

                code = get_error_code(
                    error
                )


                self._record(

                    provider="google",

                    model=model,

                    status="failed",

                    purpose=purpose,

                    fingerprint=fingerprint,

                    attempt=attempt,

                    error=error_text
                )


                print(
                    f"[GATEWAY] Failed "
                    f"(HTTP {code or 'unknown'}): "
                    f"{error_text}"
                )


                # =================================================
                # 401 / 403
                #
                # Actual provider credentials / permissions issue.
                # Other Gemini models will almost certainly fail
                # with the same key.
                #
                # Move to OpenRouter.
                # =================================================

                if is_auth_error(
                    error_text
                ):

                    print(
                        "[GATEWAY] Gemini authentication/"
                        "permission failure."
                    )

                    print(
                        "[GATEWAY] Moving to next provider."
                    )

                    return (
                        None,
                        True
                    )


                # =================================================
                # 404
                #
                # Retired or inaccessible MODEL.
                #
                # Do NOT stop Gemini.
                # Immediately try next discovered model.
                # =================================================

                if is_model_unavailable_error(
                    error_text
                ):

                    print(
                        "[GATEWAY] Model unavailable or retired."
                    )

                    print(
                        "[GATEWAY] Trying next Gemini model."
                    )

                    return (
                        None,
                        False
                    )


                # =================================================
                # 429 WITH ZERO QUOTA
                #
                # Model exists, but current project has no quota.
                #
                # Retrying is useless.
                # Move immediately to next model.
                # =================================================

                if is_zero_quota_error(
                    error_text
                ):

                    print(
                        "[GATEWAY] This model has zero available "
                        "quota for the current project."
                    )

                    print(
                        "[GATEWAY] Skipping model and continuing."
                    )

                    return (
                        None,
                        False
                    )


                # =================================================
                # TRANSIENT 408 / 429 / 5xx
                #
                # Retry this model.
                # After retry exhaustion, continue to NEXT model.
                # =================================================

                if is_transient_error(
                    error_text
                ):

                    if (
                        attempt
                        < GEMINI_MAX_RETRIES
                    ):

                        print(
                            f"[GATEWAY] Temporary failure "
                            f"({attempt}/{GEMINI_MAX_RETRIES})."
                        )

                        backoff_sleep(
                            attempt
                        )

                        continue


                    print(
                        "[GATEWAY] Retry limit reached."
                    )

                    print(
                        "[GATEWAY] Continuing to next Gemini model."
                    )

                    return (
                        None,
                        False
                    )


                # =================================================
                # BAD JSON
                # =================================================

                if isinstance(
                    error,
                    json.JSONDecodeError
                ):

                    if (
                        attempt
                        < GEMINI_MAX_RETRIES
                    ):

                        print(
                            "[GATEWAY] Model returned invalid JSON."
                        )

                        print(
                            "[GATEWAY] Retrying same model."
                        )

                        continue


                # =================================================
                # UNKNOWN MODEL-SPECIFIC FAILURE
                #
                # Don't kill gateway.
                # =================================================

                print(
                    "[GATEWAY] Unknown/model-specific failure."
                )

                print(
                    "[GATEWAY] Continuing to next Gemini model."
                )


                return (
                    None,
                    False
                )


        return (
            None,
            False
        )


        # ========================================================
    # OPENROUTER MODEL CALL
    # ========================================================

    def _try_openrouter_model(
        self,
        model_info: Dict[str, Any],
        system_instruction: str,
        user_prompt: str,
        temperature: float,
        fingerprint: str,
        purpose: str
    ):

        model_id = model_info[
            "id"
        ]
        required = len((system_instruction + user_prompt).encode()) + self.max_output_tokens
        context_length = model_info.get('context_length', 0)
        if context_length and context_length < required:
            self._record('openrouter', model_id, 'skipped', purpose, fingerprint, 0, error='Insufficient context capacity')
            return None, False

        supports_response_format = (
            model_info.get(
                "supports_response_format",
                False
            )
        )


        # ----------------------------------------------------
        # EXACT SAME SEMANTIC CONTEXT
        # ----------------------------------------------------

        messages = [

            {
                "role":
                    "system",

                "content":
                    system_instruction
            },

            {
                "role":
                    "user",

                "content":
                    user_prompt
            }
        ]


        endpoint = (
            "https://openrouter.ai/"
            "api/v1/chat/completions"
        )


        headers = {

            "Authorization":
                f"Bearer {OPENROUTER_API_KEY}",

            "Content-Type":
                "application/json",

            "X-OpenRouter-Title":
                "LLM Security Planning Agent"
        }


        # ----------------------------------------------------
        # If structured-output mode produces a compatibility
        # error, retry this model WITHOUT response_format.
        #
        # The system prompt still demands valid JSON.
        # ----------------------------------------------------

        modes = []

        if supports_response_format:
            modes.append(True)

        modes.append(False)

        modes = list(
            dict.fromkeys(modes)
        )


        for use_response_format in modes:

            for attempt in range(
                1,
                OPENROUTER_MAX_RETRIES + 1
            ):

                payload = {
                    "max_tokens": self.max_output_tokens,

                    "model":
                        model_id,

                    "messages":
                        messages,

                    "temperature":
                        temperature,

                    "provider": {

                        # OpenRouter itself may fail over
                        # between providers serving this model.
                        "allow_fallbacks":
                            True
                    }
                }


                if use_response_format:

                    payload[
                        "response_format"
                    ] = {
                        "type":
                            "json_object"
                    }


                if self.before_call:
                    self.before_call(system_instruction, user_prompt)
                try:

                    response = requests.post(

                        endpoint,

                        headers=headers,

                        json=payload,

                        timeout=self.timeout_seconds
                    )


                    # ========================================
                    # HTTP ERROR
                    # ========================================

                    if response.status_code >= 400:

                        error_text = redact(

                            f"{response.status_code} "
                            f"{response.text}"
                        )


                        self._record(

                            provider=(
                                "openrouter"
                            ),

                            model=model_id,

                            status="failed",

                            purpose=purpose,

                            fingerprint=(
                                fingerprint
                            ),

                            attempt=attempt,

                            error=error_text
                        )


                        print(
                            f"[GATEWAY] OpenRouter "
                            f"failure: {error_text}"
                        )


                        # ------------------------------------
                        # Authentication
                        # ------------------------------------

                        if (
                            response.status_code
                            in [401, 403]
                        ):

                            return (
                                None,
                                True
                            )


                        # ------------------------------------
                        # Model does not exist / unavailable
                        # ------------------------------------

                        if (
                            response.status_code
                            == 404
                        ):

                            print(
                                "[GATEWAY] OpenRouter model "
                                "unavailable. Moving on."
                            )

                            return (
                                None,
                                False
                            )


                        # ------------------------------------
                        # Structured-output incompatibility
                        # ------------------------------------

                        if (
                            response.status_code
                            == 400
                            and use_response_format
                        ):

                            print(
                                "[GATEWAY] Structured JSON "
                                "mode unsupported."
                            )

                            print(
                                "[GATEWAY] Retrying model "
                                "using prompt-enforced JSON."
                            )

                            break


                        # ------------------------------------
                        # Temporary errors
                        # ------------------------------------

                        if is_zero_quota_error(error_text):
                            return None, False

                        if (
                            response.status_code
                            in [
                                408,
                                429,
                                500,
                                502,
                                503,
                                504
                            ]
                        ):

                            if (
                                attempt
                                < OPENROUTER_MAX_RETRIES
                            ):

                                backoff_sleep(
                                    attempt
                                )

                                continue


                            print(
                                "[GATEWAY] Retry limit "
                                "reached for this model."
                            )

                            return (
                                None,
                                False
                            )


                        # Anything else:
                        # next model

                        return (
                            None,
                            False
                        )


                    # ========================================
                    # SUCCESS RESPONSE
                    # ========================================

                    body = response.json()
                    if self.on_usage:
                        self.on_usage(int((body.get('usage') or {}).get('total_tokens', 0) or 0))


                    choices = body.get(
                        "choices",
                        []
                    )


                    if not choices:

                        raise ValueError(
                            "OpenRouter returned no choices."
                        )


                    message = choices[
                        0
                    ].get(
                        "message",
                        {}
                    )


                    content = message.get(
                        "content",
                        ""
                    )


                    result = parse_json_response(
                        content
                    )


                    actual_model = body.get(
                        "model",
                        model_id
                    )


                    metadata = {

                        "provider":
                            "openrouter",

                        "requested_model":
                            model_id,

                        "model":
                            actual_model,

                        "attempt":
                            attempt,

                        "purpose":
                            purpose,

                        "context_fingerprint":
                            fingerprint
                    }


                    self._record(

                        provider="openrouter",

                        model=model_id,

                        actual_model=(
                            actual_model
                        ),

                        status="success",

                        purpose=purpose,

                        fingerprint=(
                            fingerprint
                        ),

                        attempt=attempt
                    )
                    metadata['fallback'] = self.history[-1]['fallback']


                    print(
                        f"[GATEWAY] SUCCESS â†’ "
                        f"OpenRouter / {actual_model}"
                    )


                    return (
                        (
                            result,
                            metadata
                        ),
                        False
                    )


                except json.JSONDecodeError as error:

                    error_text = (
                        f"Invalid JSON: {error}"
                    )


                    self._record(

                        provider="openrouter",

                        model=model_id,

                        status="failed",

                        purpose=purpose,

                        fingerprint=(
                            fingerprint
                        ),

                        attempt=attempt,

                        error=error_text
                    )


                    print(
                        "[GATEWAY] Model returned "
                        "invalid JSON."
                    )


                    if (
                        attempt
                        < OPENROUTER_MAX_RETRIES
                    ):

                        continue


                except requests.RequestException as error:

                    error_text = redact(str(error))


                    self._record(

                        provider="openrouter",

                        model=model_id,

                        status="failed",

                        purpose=purpose,

                        fingerprint=(
                            fingerprint
                        ),

                        attempt=attempt,

                        error=error_text
                    )


                    print(
                        "[GATEWAY] Network error: "
                        f"{error_text}"
                    )


                    if (
                        attempt
                        < OPENROUTER_MAX_RETRIES
                    ):

                        backoff_sleep(
                            attempt
                        )

                        continue


                except Exception as error:

                    error_text = redact(str(error))


                    self._record(

                        provider="openrouter",

                        model=model_id,

                        status="failed",

                        purpose=purpose,

                        fingerprint=(
                            fingerprint
                        ),

                        attempt=attempt,

                        error=error_text
                    )


                    print(
                        "[GATEWAY] Model error: "
                        f"{error_text}"
                    )


                    if (
                        attempt
                        < OPENROUTER_MAX_RETRIES
                    ):

                        continue


            # Continue to next structured/plain mode


        print(
            "[GATEWAY] OpenRouter model exhausted."
        )

        return (
            None,
            False
        )


    # ========================================================
    # SAVE HISTORY
    # ========================================================

    def save_history(
        self,
        filename: str = "planner_llm_history.json"
    ):

        try:

            with open(
                filename,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    redact(self.history),
                    file,
                    indent=2,
                    ensure_ascii=False
                )

            print(
                f"[GATEWAY] History saved â†’ {filename}"
            )

        except Exception as error:

            print(
                "[GATEWAY] Could not save history:"
            )

            print(
                error
            )
