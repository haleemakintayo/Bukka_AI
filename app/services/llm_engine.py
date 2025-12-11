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
    temperature=0, 
    groq_api_key=settings.GROQ_API_KEY, 
    model_name="meta-llama/llama-4-scout-17b-16e-instruct"
)

# --- PART A: THE ORDER BOT (Standard Chain) ---
order_parser = JsonOutputParser(pydantic_object=AIResponse)

order_system_prompt = """
You are 'Auntie Chioma', a Nigerian food vendor assistant.
Menu: {menu}

Tasks:
1. Identify if user is ordering. Extract items.
2. If asking questions, answer politely.
3. Speak in Nigerian English/Pidgin.

Output JSON only.
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