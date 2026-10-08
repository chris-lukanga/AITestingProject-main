import os
import json
import hashlib
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

from llm_gateway import LLMGateway
from web_research import WebResearcher
from agents.planner_agent import PlannerAgent
from services.security import redact


load_dotenv()


class Orchestrator:

    def __init__(self):

        # ====================================================
        # ENVIRONMENT
        # ====================================================

        tavily_key = os.getenv(
            "TAVILY_API_KEY"
        )


        if not tavily_key:
            raise ValueError(
                "TAVILY_API_KEY is missing from .env"
            )


        # ====================================================
        # OUTPUT DIRECTORIES
        # ====================================================

        self.output_dir = Path(
            "outputs"
        )

        self.checkpoint_dir = (
            self.output_dir
            / "checkpoints"
        )


        self.output_dir.mkdir(
            exist_ok=True
        )

        self.checkpoint_dir.mkdir(
            parents=True,
            exist_ok=True
        )


        # ====================================================
        # SHARED INFRASTRUCTURE
        # ====================================================

        print(
            "[ORCHESTRATOR] Initializing shared LLM gateway..."
        )

        self.gateway = LLMGateway()


        print(
            "[ORCHESTRATOR] Initializing web researcher..."
        )

        self.researcher = WebResearcher(

            api_key=tavily_key,

            max_total_sources=int(
                os.getenv(
                    "MAX_RESEARCH_SOURCES",
                    "20"
                )
            ),

            max_source_chars=int(
                os.getenv(
                    "MAX_SOURCE_CHARS",
                    "3000"
                )
            )
        )


        # ====================================================
        # AGENTS
        # ====================================================

        print(
            "[ORCHESTRATOR] Initializing Planning Agent..."
        )

        self.planner = PlannerAgent(

            gateway=self.gateway,

            researcher=self.researcher
        )


    # ========================================================
    # LOAD TARGET
    # ========================================================

    def load_target(
        self,
        filename: str
    ) -> Dict[str, Any]:

        if not os.path.exists(
            filename
        ):
            raise FileNotFoundError(
                f"Target file not found: {filename}"
            )


        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as file:

            return redact(json.load(file))


    # ========================================================
    # TARGET FINGERPRINT
    # ========================================================

    def target_fingerprint(
        self,
        context: Dict[str, Any]
    ) -> str:

        normalized = json.dumps(

            context,

            sort_keys=True,

            ensure_ascii=False
        )


        return hashlib.sha256(
            normalized.encode(
                "utf-8"
            )
        ).hexdigest()[:16]


    # ========================================================
    # CHECKPOINT PATH
    # ========================================================

    def checkpoint_path(
        self,
        context: Dict[str, Any]
    ) -> Path:

        fingerprint = (
            self.target_fingerprint(
                context
            )
        )


        return (
            self.checkpoint_dir
            / f"planner_{fingerprint}.json"
        )


    # ========================================================
    # SAVE JSON
    # ========================================================

    def save_json(
        self,
        path: Path,
        data: Any
    ):

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                redact(data),
                file,
                indent=2,
                ensure_ascii=False
            )


    # ========================================================
    # DISPLAY TARGET
    # ========================================================

    def display_target(
        self,
        context: Dict[str, Any]
    ):

        application = context.get(
            "application",
            {}
        )

        llm = context.get(
            "llm",
            {}
        )

        integration = context.get(
            "integration",
            {}
        )


        print()
        print(
            "=============================================="
        )
        print(
            "TARGET APPLICATION"
        )
        print(
            "=============================================="
        )


        print(
            "Application:",
            application.get(
                "name",
                "Unknown"
            )
        )


        print(
            "Purpose:",
            application.get(
                "purpose",
                "Unknown"
            )
        )


        print(
            "Target LLM:",
            llm.get(
                "model_version",
                llm.get(
                    "model",
                    "Unknown"
                )
            )
        )


        print(
            "LLM Provider:",
            llm.get(
                "provider",
                "Unknown"
            )
        )


        print(
            "Integration:",
            integration.get(
                "type",
                "Unknown"
            )
        )


    # ========================================================
    # GET OR CREATE RESEARCH CHECKPOINT
    # ========================================================

    def get_planner_evidence(
        self,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:

        checkpoint = (
            self.checkpoint_path(
                context
            )
        )


        refresh = (
            os.getenv(
                "REFRESH_RESEARCH",
                "false"
            ).lower()
            == "true"
        )


        # ====================================================
        # REUSE PREVIOUS EVIDENCE
        # ====================================================

        if (
            checkpoint.exists()
            and not refresh
        ):

            print()
            print(
                "[ORCHESTRATOR] Planner checkpoint found."
            )

            print(
                "[ORCHESTRATOR] Reusing previous web research."
            )


            with open(
                checkpoint,
                "r",
                encoding="utf-8"
            ) as file:

                return json.load(
                    file
                )


        # ====================================================
        # CREATE NEW EVIDENCE
        # ====================================================

        evidence = (
            self.planner.prepare_evidence(
                context
            )
        )


        self.save_json(
            checkpoint,
            evidence
        )


        print()
        print(
            f"[ORCHESTRATOR] Research checkpoint saved:"
        )

        print(
            checkpoint
        )


        return evidence


    # ========================================================
    # RUN
    # ========================================================

    def run(
        self,
        target_file: str
    ) -> Dict[str, Any]:

        print()
        print(
            "=============================================="
        )
        print(
            "LLM SECURITY ORCHESTRATOR"
        )
        print(
            "=============================================="
        )


        context = self.load_target(
            target_file
        )


        self.display_target(
            context
        )


        try:

            # =================================================
            # PHASE 1
            # Planning research
            # =================================================

            print()
            print(
                "[ORCHESTRATOR] Starting Planning Agent..."
            )


            evidence = (
                self.get_planner_evidence(
                    context
                )
            )


            # =================================================
            # PHASE 2
            # Final plan
            # =================================================

            plan, planner_metadata = (
                self.planner.create_plan(
                    context=context,
                    evidence=evidence
                )
            )


            # =================================================
            # SAVE FINAL PLAN
            # =================================================

            plan_path = (
                self.output_dir
                / "security_test_plan.json"
            )


            self.save_json(
                plan_path,
                plan
            )


            # =================================================
            # SAVE RUN METADATA
            # =================================================

            run_metadata = {

                "target_fingerprint":
                    self.target_fingerprint(
                        context
                    ),

                "planner_model":
                    planner_metadata,

                "research_sources":
                    len(
                        evidence.get(
                            "research",
                            []
                        )
                    )
            }


            metadata_path = (
                self.output_dir
                / "planner_run_metadata.json"
            )


            self.save_json(
                metadata_path,
                run_metadata
            )


            # =================================================
            # OUTPUT SUMMARY
            # =================================================

            print()
            print(
                "=============================================="
            )
            print(
                "PLANNER COMPLETE"
            )
            print(
                "=============================================="
            )


            print(
                f"Provider used: "
                f"{planner_metadata.get('provider')}"
            )


            print(
                f"Model used: "
                f"{planner_metadata.get('model')}"
            )


            print(
                f"Context fingerprint: "
                f"{planner_metadata.get('context_fingerprint')}"
            )


            print(
                f"Research sources: "
                f"{len(evidence.get('research', []))}"
            )


            print(
                f"\nSecurity plan saved to:"
            )

            print(
                plan_path
            )


            self.display_priorities(
                plan
            )


            return plan


        finally:

            # =================================================
            # ALWAYS SAVE MODEL HISTORY
            # EVEN WHEN AN AGENT FAILS
            # =================================================

            history_path = (
                self.output_dir
                / "llm_history.json"
            )


            try:

                self.gateway.save_history(
                    str(history_path)
                )

            except Exception as error:

                print(
                    "[ORCHESTRATOR] Could not save "
                    f"gateway history: {redact(str(error))}"
                )


    # ========================================================
    # DISPLAY TEST PRIORITIES
    # ========================================================

    def display_priorities(
        self,
        plan: Dict[str, Any]
    ):

        priorities = plan.get(
            "test_priorities",
            []
        )


        print()
        print(
            "=============================================="
        )
        print(
            "TOP TESTING PRIORITIES"
        )
        print(
            "=============================================="
        )


        if not priorities:

            print(
                "No priorities returned."
            )

            return


        for item in priorities:

            print()


            print(
                f"#{item.get('rank', '?')} "
                f"[{item.get('priority', 'UNKNOWN')}] "
                f"{item.get('risk_area', 'Unknown')}"
            )


            print(
                f"Component: "
                f"{item.get('component', 'Unknown')}"
            )


            print(
                f"Reason: "
                f"{item.get('reason', '')}"
            )


            print(
                f"Testing goal: "
                f"{item.get('testing_goal', '')}"
            )
