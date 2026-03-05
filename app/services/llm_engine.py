# app/services/llm_engine.py
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langgraph.prebuilt import create_react_agent

from app.core.config import settings
from app.models.schemas import OrderExtractionResponse
from app.services.ai_tools import consultant_tools

# 1. Initialize Groq Model
llm = ChatGroq(
    temperature=0.5, 
    groq_api_key=settings.GROQ_API_KEY, 
    model_name="meta-llama/llama-4-maverick-17b-128e-instruct"
)

# --- PART A: Extraction-only chain ---
order_parser = JsonOutputParser(pydantic_object=OrderExtractionResponse)

order_system_prompt = """
You are an information extraction engine for Bukka AI.

Menu reference:
{menu}

Task:
Extract user intent and item quantities only. Do not calculate totals, do not write conversational replies.

Allowed intents:
- order
- inquiry
- payment
- chitchat
- unknown

Rules:
1. Output valid JSON only. No markdown.
2. Use this exact schema:
{{
  "intent": "order|inquiry|payment|chitchat|unknown",
  "items": ["item_a", "item_b"],
  "qty": [2, 1]
}}
3. Keep items and qty arrays aligned by index.
4. If quantity is missing, infer 1.
5. If no menu item is mentioned, return empty arrays.
6. Map slang/short names to likely menu names where possible.
"""

order_prompt = ChatPromptTemplate.from_messages([
    ("system", order_system_prompt),
    ("human", "{user_input}"),
])

order_chain = order_prompt | llm | order_parser

# --- PART B: THE CONSULTANT AGENT (Simplified) ---

# We removed the 'messages_modifier' to avoid version errors.
# We will pass the system prompt in routes.py instead.
consultant_agent = create_react_agent(
    llm, 
    tools=consultant_tools
)
