from pydantic import BaseModel
from typing import List, Optional, Any, Dict

class SummarizeRequest(BaseModel):
    source: Dict[str, Any]

class InsightsRequest(BaseModel):
    action: str
    source: Dict[str, Any]
    question: Optional[str] = None
    compareWith: Optional[Dict[str, Any]] = None

class CompareRequest(BaseModel):
    sources: Optional[List[Dict[str, Any]]] = None
    contextItems: Optional[List[Dict[str, Any]]] = None
    selectedSourceIds: Optional[List[str]] = []

class BriefRequest(BaseModel):
    topic: str
    sources: List[Dict[str, Any]]
    selectedSourceIds: Optional[List[str]] = []

class EntitiesRequest(BaseModel):
    topic: Optional[str] = "Knowledge Graph Analysis"
    sources: Optional[List[Dict[str, Any]]] = None
    contextItems: Optional[List[Dict[str, Any]]] = None
    selectedSourceIds: Optional[List[str]] = []

class TimelineRequest(BaseModel):
    topic: Optional[str] = "Research Analysis"
    sources: Optional[List[Dict[str, Any]]] = None
    contextItems: Optional[List[Dict[str, Any]]] = None
    selectedSourceIds: Optional[List[str]] = []

class ReportRequest(BaseModel):
    topic: Optional[str] = "Research Intelligence Report"
    sources: Optional[List[Dict[str, Any]]] = None
    contextItems: Optional[List[Dict[str, Any]]] = None
    selectedSourceIds: Optional[List[str]] = []

class ChatActionRequest(BaseModel):
    action: str
    topic: Optional[str] = "Research Topic"
    contextItems: Optional[List[Dict[str, Any]]] = []
    sources: Optional[List[Dict[str, Any]]] = []

class ChatRequest(BaseModel):
    source: Dict[str, Any]
    message: str
    history: Optional[List[Dict[str, Any]]] = []
