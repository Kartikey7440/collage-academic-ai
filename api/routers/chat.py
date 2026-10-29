"""POST /api/v1/chat: ask the academic assistant a question.

Students and faculty only. The user's scope comes from the login token, never
from the request body.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.agent.agent import answer_question
from api.deps import ScopedIdentity, get_current_identity, get_db

router = APIRouter(tags=["chat"])


class ChatTurn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(max_length=1000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


class ToolCallInfo(BaseModel):
    name: str
    args: dict


class ChatResponse(BaseModel):
    reply: str
    tools_used: list[ToolCallInfo]
    fallback: bool
    elapsed_ms: int
    assistant_time: str


@router.post("/chat", response_model=ChatResponse, summary="Ask the academic assistant")
async def chat(
    body: ChatRequest,
    identity: ScopedIdentity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    if identity.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The chat assistant is available to students and faculty.",
        )
    result = await answer_question(
        db,
        identity,
        body.message.strip(),
        [turn.model_dump() for turn in body.history],
    )
    return ChatResponse(**result)