from dotenv import load_dotenv
import os
from langchain_groq import ChatGroq
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL")

llm=ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY)

answer = llm.invoke("What is the capital of France?")

print(answer.content)