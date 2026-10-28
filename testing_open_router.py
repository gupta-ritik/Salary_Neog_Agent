import os
from dotenv import load_dotenv
from langchain_openrouter import ChatOpenRouter

load_dotenv()

llm = ChatOpenRouter(
    model=os.getenv("MODEL", "openrouter/free"),
    api_key=os.getenv("OPENROUTER_API_KEY"),
    temperature=0.2,
    max_tokens=300,
)

response = llm.invoke(
    "Explain LangGraph in simple terms with a Python example."
)

print(response.content)
# print("Usage:", response.usage_metadata)
# print("Response metadata:", response.response_metadata)
# print("Response content:", response.content)