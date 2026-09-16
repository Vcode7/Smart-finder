from pydantic import BaseModel
from typing import List, Optional, Any, Dict, Union

class SearchRequest(BaseModel):
    topic: str
    source: Optional[str] = "internet" # "internet", "local", "both"

class LocalSearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 10

class MatchingFrame(BaseModel):
    id: str
    frameNumber: int = 1
    sceneId: int = 1
    timestamp: float = 0.0
    framePath: str
    similarity: float
    isFaceMatch: Optional[bool] = None
    faceSimilarity: Optional[float] = None
    visualDescription: Optional[str] = None

class CrossSourceItem(BaseModel):
    id: str
    sourceId: str
    category: str
    title: str
    originalName: str
    fileType: str
    fileSize: int
    uploadDate: str
    snippet: str
    relevanceScore: float
    pageNum: Optional[int] = None
    timestamp: Optional[float] = None

class MultimodalSearchResultItem(BaseModel):
    id: str
    sourceId: str
    category: str
    title: str
    originalName: str
    fileType: str
    fileSize: int
    uploadDate: str
    relevanceScore: float
    snippet: str
    fullContext: Optional[str] = None
    isFaceMatch: Optional[bool] = None
    faceSimilarity: Optional[float] = None
    detectedEntity: Optional[str] = None
    sectionTitle: Optional[str] = None
    pageNum: Optional[int] = None
    pageCount: Optional[int] = None
    startTime: Optional[float] = None
    endTime: Optional[float] = None
    duration: Optional[float] = None
    matchingFrames: Optional[List[MatchingFrame]] = None
    primaryFrame: Optional[MatchingFrame] = None
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    ocrText: Optional[str] = None
    relatedCrossSources: Optional[List[CrossSourceItem]] = None

class MultimodalSearchResponse(BaseModel):
    query: str
    queryType: str
    queryImagePreview: Optional[str] = None
    documents: List[MultimodalSearchResultItem] = []
    videos: List[MultimodalSearchResultItem] = []
    audio: List[MultimodalSearchResultItem] = []
    images: List[MultimodalSearchResultItem] = []
    total: int = 0

class FetchMoreRequest(BaseModel):
    topic: str
    type: str
    currentCount: Optional[int] = 8
    targetLimit: Optional[int] = None
    offset: Optional[int] = 0
    page: Optional[int] = 1
    pageToken: Optional[str] = None
    existingUrls: Optional[List[str]] = []
    existingTitles: Optional[List[str]] = []

class SynthesizeRequest(BaseModel):
    query: str
    selectedLocalDocs: Optional[List[Dict[str, Any]]] = []
    selectedInternetSources: Optional[List[Dict[str, Any]]] = []

class VideoSearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 10
