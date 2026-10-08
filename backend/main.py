import sys

from orchestrator import Orchestrator


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'serve':
        import uvicorn
        uvicorn.run('app:app', host='127.0.0.1', port=8000)
        return

    # ========================================================
    # TARGET FILE
    # ========================================================

    if len(sys.argv) > 1:

        target_file = sys.argv[1]

    else:

        target_file = "example.json"


    print(
        f"[MAIN] Target configuration: {target_file}"
    )


    # ========================================================
    # CREATE ORCHESTRATOR
    # ========================================================

    orchestrator = Orchestrator()


    # ========================================================
    # START WORKFLOW
    # ========================================================

    orchestrator.run(
        target_file
    )


if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\n[MAIN] Execution stopped by user."
        )

    except Exception as error:

        print()
        print(
            "=============================================="
        )
        print(
            "ORCHESTRATOR ERROR"
        )
        print(
            "=============================================="
        )

        print(
            f"{type(error).__name__}: {error}"
        )
        sys.exit(1)
