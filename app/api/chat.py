from fastapi import APIRouter

from app.agent.service import ask_agent
from app.schemas.agent import ChatRequest, ChatResponse


router = APIRouter(prefix="/api/v1", tags=["agent"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    return await ask_agent(
        request.question,
        owner_id="local",
    )