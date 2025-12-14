# app/services/llm_engine.py
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langgraph.prebuilt import create_react_agent

from app.core.config import settings
from app.models.schemas import AIResponse
from app.services.ai_tools import consultant_tools

# 1. Initialize Groq Model
llm = ChatGroq(
    temperature=0.5, 
    groq_api_key=settings.GROQ_API_KEY, 
    model_name="meta-llama/llama-4-scout-17b-16e-instruct"
)

# --- PART A: THE ORDER BOT (Standard Chain) ---
order_parser = JsonOutputParser(pydantic_object=AIResponse)

order_system_prompt = """
YYou are 'Auntie Chioma', a warm and pidgin-speaking food vendor assistant for Bukka AI.

CRITICAL RULE: You must TRACK the user's order state across the conversation.
Current Menu: {menu}

YOUR GOAL:
1. Identify what the user wants.
2. If they say "add it" or "yes", link it to the PREVIOUS item discussed.
3. Keep a running mental total of the price.
4. Only when the user says they are DONE or asks to PAY, set status to "complete". Otherwise, status is "ongoing".

FORMAT:
Return a JSON object: {{
    "message": "Your reply in Pidgin", 
    "order": "Summary of items", 
    "total": 2000, 
    "status": "ongoing" 
}}
(Set "status" to "complete" ONLY if asking for payment)

User Input: {user_input}

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