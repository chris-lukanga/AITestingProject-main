import os
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

tavily = TavilyClient(
    api_key=os.getenv("TAVILY_API_KEY")
)

results = tavily.search(
    query="time right now",
    max_results=5
)

for result in results["results"]:
    print("\nTITLE:")
    print(result["title"])

    print("\nURL:")
    print(result["url"])

    print("\nCONTENT:")
    print(result["content"])

    print("-" * 80)