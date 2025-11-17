"""
Database Schemas for RFP → Proposal app

Each Pydantic model corresponds to a MongoDB collection.
Collection name is the lowercase class name.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Rfp(BaseModel):
    """
    RFPs uploaded by users
    Collection name: "rfp"
    """
    filename: str = Field(..., description="Original file name")
    content: str = Field(..., description="Extracted plain text content of the RFP")
    filesize: Optional[int] = Field(None, description="Size in bytes")
    mimetype: Optional[str] = Field(None, description="Uploaded file MIME type")
    uploaded_by: Optional[str] = Field(None, description="Uploader identifier if available")

class Proposal(BaseModel):
    """
    Proposals generated from RFPs
    Collection name: "proposal"
    """
    rfp_id: str = Field(..., description="Reference to the RFP document id")
    title: str = Field(..., description="Proposal title")
    summary: str = Field(..., description="Executive summary")
    client_name: Optional[str] = Field(None, description="Detected client/agency name")
    project_name: Optional[str] = Field(None, description="Detected project or RFP title")
    due_date: Optional[str] = Field(None, description="Detected due date")
    sections: List[dict] = Field(default_factory=list, description="Structured proposal sections with headings and content")
    status: str = Field("generated", description="Status of the proposal")
    generated_at: Optional[datetime] = Field(default=None, description="Timestamp of generation")
