"""
Database Schemas for RFP → Proposal app

Each Pydantic model corresponds to a MongoDB collection.
Collection name is the lowercase class name.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
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
    Simple proposal artifact generated immediately after RFP upload
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

# New collections for full-feature flows
class TeamMember(BaseModel):
    """Collection name: teammember"""
    name: str
    role: str
    titleQual: Optional[str] = None
    blurb: Optional[str] = None
    bullets: Optional[str] = Field(None, description="Multi-line text, one bullet per line")
    photo_url: Optional[str] = Field(None, description="URL of uploaded photo")

class ProjectHighlight(BaseModel):
    """Collection name: projecthighlight"""
    title: str
    sector: Optional[str] = None
    summary: Optional[str] = None
    bullets: Optional[str] = Field(None, description="Multi-line bullets")

class ProposalDoc(BaseModel):
    """
    Rich proposal record matching product spec
    Collection name: "proposaldoc"
    """
    clientName: str
    projectTitle: str
    rfpId: Optional[str] = Field(None, description="Reference to uploaded RFP record")
    rfpFileUrl: Optional[str] = None
    placeholdersJson: Any
    docxFileUrl: Optional[str] = None
    pdfFileUrl: Optional[str] = None
    status: str = Field("draft", description="draft/sent")
    version: int = 1
    teamMemberIds: List[str] = Field(default_factory=list)
    projectHighlightIds: List[str] = Field(default_factory=list)
