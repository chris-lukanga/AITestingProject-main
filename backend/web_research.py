from typing import Any, Dict, List

from tavily import TavilyClient
from services.security import redact


class WebResearcher:

    def __init__(
        self,
        api_key: str,
        max_total_sources: int = 20,
        max_source_chars: int = 3000
    ):
        self.client = TavilyClient(
            api_key=api_key
        )

        self.max_total_sources = max_total_sources
        self.max_source_chars = max_source_chars


    # ========================================================
    # SINGLE SEARCH
    # ========================================================

    def search(
        self,
        query: str,
        max_results: int = 4
    ) -> List[Dict[str, Any]]:

        print(
            f"\n[WEB RESEARCH] {query}"
        )

        try:

            response = self.client.search(
                query=query,
                max_results=max_results
            )

            return response.get(
                "results",
                []
            )

        except Exception as error:

            print(
                f"[WEB RESEARCH WARNING] {redact(str(error))}"
            )

            return []


    # ========================================================
    # MULTIPLE SEARCHES
    # ========================================================

    def search_many(
        self,
        queries: List[str]
    ) -> List[Dict[str, Any]]:

        collected = []

        seen_urls = set()


        for query in dict.fromkeys(queries):

            results = self.search(
                query
            )


            for result in results:

                url = result.get(
                    "url",
                    ""
                )

                if not url:
                    continue


                # Avoid duplicate sources
                if url in seen_urls:
                    continue


                seen_urls.add(
                    url
                )


                content = result.get(
                    "content",
                    ""
                )

                # Prevent huge LLM contexts
                content = content[
                    :self.max_source_chars
                ]


                collected.append({

                    "research_query":
                        query,

                    "title":
                        result.get(
                            "title",
                            ""
                        ),

                    "url":
                        url,

                    "content":
                        content
                })


                if (
                    len(collected)
                    >= self.max_total_sources
                ):

                    print(
                        f"\n[WEB RESEARCH] "
                        f"Source limit reached: "
                        f"{self.max_total_sources}"
                    )

                    return collected


        return collected
