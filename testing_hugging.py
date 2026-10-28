import torch
from transformers import pipeline
from langchain_huggingface import HuggingFacePipeline

model_id = "Qwen/Qwen2.5-0.5B-Instruct"

device = 0 if torch.cuda.is_available() else -1

pipe = pipeline(
    "text-generation",
    model=model_id,
    device=device,
    max_new_tokens=200,
    do_sample=False,
    return_full_text=False
)

llm = HuggingFacePipeline(pipeline=pipe)

response = llm.invoke(
    "Explain RAG in LangChain in five bullet points."
)

print(response)
