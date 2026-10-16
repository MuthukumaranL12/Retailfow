from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.db import db
from app.security import get_current_user
from app.security_controls import rate_limit
from app.services.chatbot_service import (
    ChatbotError,
    PageContext,
    answer_chat_question,
    confirm_staged_action,
)

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatQuery(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    page_context: PageContext | None = None
    conversation_id: str | None = Field(default=None, min_length=1, max_length=100)


class ConfirmActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=100)
    confirmed: bool


@router.get("/conversations")
async def get_conversations(current_user: dict = Depends(get_current_user)):
    items = list(
        db.conversations.find(
            {"owner_email": current_user["email"]},
            {"_id": 0, "conversation_id": 1, "title": 1, "created_at": 1, "updated_at": 1},
        ).sort("updated_at", -1).limit(50)
    )
    return {"conversations": items}


@router.post("/conversations", status_code=201)
async def create_conversation(current_user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    conversation = {
        "conversation_id": uuid4().hex,
        "owner_email": current_user["email"],
        "title": "New conversation",
        "messages": [],
        "pending_actions": [],
        "created_at": now,
        "updated_at": now,
    }
    db.conversations.insert_one(conversation)
    conversation.pop("owner_email")
    return conversation


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)):
    conversation = db.conversations.find_one(
        {"conversation_id": conversation_id, "owner_email": current_user["email"]},
        {"_id": 0, "owner_email": 0},
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)):
    result = db.conversations.delete_one(
        {"conversation_id": conversation_id, "owner_email": current_user["email"]}
    )
    if result.deleted_count != 1:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"message": "Conversation deleted", "conversation_id": conversation_id}


@router.post("/conversations/{conversation_id}/confirm")
async def confirm_chat_action(
    conversation_id: str,
    payload: ConfirmActionRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return confirm_staged_action(
            conversation_id, payload.action_id, current_user, payload.confirmed
        )
    except ChatbotError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/query", dependencies=[Depends(rate_limit(30, 60))])
async def query_chat(payload: ChatQuery, current_user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    conversation_id = payload.conversation_id
    if conversation_id:
        conversation = db.conversations.find_one(
            {"conversation_id": conversation_id, "owner_email": current_user["email"]}
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation_id = uuid4().hex
        conversation = {
            "conversation_id": conversation_id,
            "owner_email": current_user["email"],
            "title": payload.question[:80],
            "messages": [],
            "pending_actions": [],
            "created_at": now,
            "updated_at": now,
        }
        db.conversations.insert_one(conversation)

    history = []
    for message in conversation.get("messages", [])[-12:]:
        if isinstance(message.get("question"), str):
            history.append({"role": "user", "content": message["question"]})
        if isinstance(message.get("answer"), str):
            history.append({"role": "assistant", "content": message["answer"]})
    try:
        response = await answer_chat_question(
            payload.question,
            current_user,
            payload.page_context.model_dump(exclude_none=True) if payload.page_context else None,
            history=history,
            conversation_id=conversation_id,
        )
    except ChatbotError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    message = {
        "question": payload.question,
        "answer": response["answer"],
        "created_at": now,
        "page_context": payload.page_context.model_dump(exclude_none=True) if payload.page_context else None,
        "tool_results": response.get("items", []),
    }
    db.conversations.update_one(
        {"conversation_id": conversation_id, "owner_email": current_user["email"]},
        {
            "$push": {"messages": {"$each": [message], "$slice": -50}},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    return {**response, "conversation_id": conversation_id}
