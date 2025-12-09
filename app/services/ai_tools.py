# app/services/ai_tools.py
from langchain_community.utilities import SerpAPIWrapper
from langchain.agents import Tool
from app.core.config import settings

search = SerpAPIWrapper(serpapi_api_key=settings.SERPAPI_API_KEY)

def get_campus_events(query: str):
    """Checks for events to predict food demand."""
    return search.run(f"Events in {query} today")

def check_competitor_prices(query: str):
    """Checks market prices for food."""
    return search.run(f"Price of {query} in Lagos restaurants")

# List of tools exported for the Agent
consultant_tools = [
    Tool(
        name="Campus_Events_Finder",
        func=get_campus_events,
        description="Finds events on campus. Input: Location name."
    ),
    Tool(
        name="Market_Price_Check",
        func=check_competitor_prices,
        description="Checks food prices. Input: Food name."
    )
]