# app/services/llm_engine.py
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain.agents import initialize_agent, AgentType

from app.core.config import settings
from app.models.schemas import AIResponse
from app.services.ai_tools import consultant_tools

# 1. Initialize Groq Model
llm = ChatGroq(
    temperature=0, 
    groq_api_key=settings.GROQ_API_KEY, 
    model_name="llama3-8b-8192"
)

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

# 3. Setup Business Consultant Agent (Smart Agent)
consultant_agent = initialize_agent(
    consultant_tools,
    llm,
    agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
    handle_parsing_errors=True
)