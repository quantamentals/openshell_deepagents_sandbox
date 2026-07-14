"""OpenShell Deep Agent.

General-purpose coding and analysis agent using OpenShell as the on-prem
sandbox provider. Executes code inside a policy-governed OpenShell sandbox
with local filesystem persistence for memory and skills.

Quick start:
  1. Start or select a gateway: openshell gateway start
  2. (Optional) Pre-create a sandbox: openshell sandbox create --name my-sandbox --keep --policy policy.yaml
     Then set: export OPENSHELL_SANDBOX_NAME=my-sandbox
  3. Run: uv run langgraph dev --allow-blocking
     Or invoke in Python: from src.agent import agent
"""

import os
from datetime import datetime

from deepagents import create_deep_agent
from langchain_ollama import ChatOllama

from src.backend import create_backend
from src.prompts import AGENT_INSTRUCTIONS

current_date = datetime.now().strftime("%Y-%m-%d")

_ollama_base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
_ollama_key = os.getenv("OLLAMA_API_KEY")
_chat_kwargs: dict = {
    "model": os.getenv("OLLAMA_MODEL", "nemotron-3-super:cloud"),
    "base_url": _ollama_base,
    "temperature": 0.1,
    "num_predict": 16384,
}
if _ollama_key:
    _chat_kwargs["client_kwargs"] = {
        "headers": {"Authorization": f"Bearer {_ollama_key}"},
    }

model = ChatOllama(**_chat_kwargs)

agent = create_deep_agent(
    model=model,
    system_prompt=AGENT_INSTRUCTIONS.format(date=current_date),
    memory=["/memory/AGENTS.md"],
    backend=create_backend,
)
