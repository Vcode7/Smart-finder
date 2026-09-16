from pydantic import BaseModel
from typing import List, Optional, Any, Dict

class KnowledgeSourceBase(BaseModel):
    id: str
    filename: str
    original_name: str
    file_type: str
    file_size: int
    upload_date: str
    uploaded_by: str
    processing_status: str
    error_message: Optional[str] = None
    chunk_count: int = 0
    transcript_count: int = 0
    face_count: int = 0
    frame_count: int = 0
    duration_seconds: Optional[float] = None
    page_count: Optional[int] = None
    uploader_name: Optional[str] = None

class DocumentSectionResponse(BaseModel):
    id: str
    section_title: Optional[str] = None
    page_num: int = 1
    order_idx: int = 0
    char_count: Optional[int] = None

class DocumentChunkResponse(BaseModel):
    id: str
    chunk_order: int = 0
    page_num: int = 1
    char_count: Optional[int] = None
    chunk_text: str

class VideoTranscriptResponse(BaseModel):
    id: str
    start_time: float
    end_time: float
    text: str

class VideoFrameResponse(BaseModel):
    id: str
    timestamp: float
    frame_number: int
    scene_id: int
    frame_path: str
    visual_description: Optional[str] = None

class KnowledgeDetailResponse(BaseModel):
    source: Dict[str, Any]
    document: Optional[Dict[str, Any]] = None
    sections: List[Dict[str, Any]] = []
    chunks: List[Dict[str, Any]] = []
    video: Optional[Dict[str, Any]] = None
    transcripts: List[Dict[str, Any]] = []
    frames: List[Dict[str, Any]] = []
    image: Optional[Dict[str, Any]] = None

class ScrapedSourceItem(BaseModel):
    id: str
    category: str
    title: str
    url: str
    snippet: str
    domain: str
    platform: str
    publishedDate: Optional[str] = None
    author: Optional[str] = None
    thumbnail: Optional[str] = None
    relevanceScore: float = 85.0

class ImportInternetItemInput(BaseModel):
    id: Optional[str] = None
    title: str
    url: str
    category: str
    snippet: Optional[str] = None
    domain: Optional[str] = None
    platform: Optional[str] = None
    publishedDate: Optional[str] = None
    author: Optional[str] = None
    thumbnail: Optional[str] = None
    fullText: Optional[str] = None

class ImportInternetRequest(BaseModel):
    sources: List[ImportInternetItemInput]

class ScrapeSearchRequest(BaseModel):
    query: str
    categories: Optional[List[str]] = ["all"]

class CheckConflictsRequest(BaseModel):
    filenames: List[str]

class ConflictItem(BaseModel):
    originalName: str
    suggestedName: str
    existsInDb: bool = True

class CheckConflictsResponse(BaseModel):
    hasConflicts: bool
    conflicts: List[ConflictItem]
