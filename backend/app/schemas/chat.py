from pydantic import BaseModel
from typing import List, Optional, Any, Dict

class ChatCreate(BaseModel):
    title: Optional[str] = "New Chat"
    searchMode: Optional[str] = "internet"

class ChatUpdate(BaseModel):
    title: str

class MessageCreate(BaseModel):
    message: str
    contextItems: Optional[List[Dict[str, Any]]] = []

class MessageResponse(BaseModel):
    id: str
    chat_id: Optional[str] = None
    role: str
    content: str
    citations_json: Optional[str] = "[]"
    created_at: Optional[str] = None
