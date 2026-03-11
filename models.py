"""
Pydantic models for request/response validation.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ============== Auth Models ==============

class UserCreate(BaseModel):
    """Request model for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=6)
    name: str = Field(..., min_length=2)


class UserLogin(BaseModel):
    """Request model for user login."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Response model for user data (no password)."""
    id: str
    email: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Response model for authentication token."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ============== Comparison Models ==============

class SubtitleEntry(BaseModel):
    """Single subtitle entry."""
    index: Optional[int] = None
    start: str
    end: str
    start_ms: int
    end_ms: int
    text: str


class ComparisonDiff(BaseModel):
    """A single diff entry between two subtitles."""
    time_start_1: Optional[str] = None
    time_end_1: Optional[str] = None
    time_start_2: Optional[str] = None
    time_end_2: Optional[str] = None
    dialogue_1: Optional[str] = None
    dialogue_2: Optional[str] = None


class ComparisonSummary(BaseModel):
    """Summary statistics for a comparison."""
    total_file1: int
    total_file2: int
    matches: int
    time_differences: int
    dialogue_differences: int
    additions: int
    removals: int
    match_percentage: float


class ComparisonResult(BaseModel):
    """Full comparison result."""
    summary: ComparisonSummary
    matches: List[Dict[str, Any]] = []
    time_differences: List[ComparisonDiff] = []
    dialogue_differences: List[ComparisonDiff] = []
    additions: List[Dict[str, Any]] = []
    removals: List[Dict[str, Any]] = []


class ComparisonCreate(BaseModel):
    """Stored comparison document."""
    user_id: str
    file1_name: str
    file2_name: str
    results: ComparisonResult
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ComparisonResponse(BaseModel):
    """Response model for a saved comparison."""
    id: str
    file1_name: str
    file2_name: str
    summary: ComparisonSummary
    status: str = "completed"  # completed, processing, failed
    created_at: datetime

    class Config:
        from_attributes = True


class ComparisonDetailResponse(BaseModel):
    """Full comparison with all details."""
    id: str
    file1_name: str
    file2_name: str
    results: ComparisonResult
    created_at: datetime

    class Config:
        from_attributes = True
