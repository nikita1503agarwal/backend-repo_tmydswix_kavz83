import os
import io
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from datetime import datetime, timezone

from database import db, create_document, get_documents
from schemas import Rfp, Proposal, TeamMember, ProjectHighlight, ProposalDoc

# Optional file parsers
try:
    import PyPDF2  # type: ignore
except Exception:
    PyPDF2 = None  # type: ignore

try:
    import docx  # python-docx
except Exception:
    docx = None  # type: ignore

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProposalResponse(BaseModel):
    proposal_id: str
    rfp_id: str


TRANSPARENT_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAuMBgThmO8kAAAAASUVORK5CYII="
)


def extract_text_from_file(upload: UploadFile, data: bytes) -> str:
    mimetype = upload.content_type or ""
    name = (upload.filename or "").lower()

    # Plain text
    if mimetype.startswith("text/") or name.endswith(".txt"):
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return data.decode(errors="replace")

    # PDF
    if (mimetype == "application/pdf" or name.endswith(".pdf")) and PyPDF2:
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(data))
            text = []
            for page in reader.pages:
                try:
                    text.append(page.extract_text() or "")
                except Exception:
                    continue
            if text:
                return "\n".join(text)
        except Exception:
            pass

    # DOCX
    if (
        mimetype in [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ]
        or name.endswith(".docx")
    ) and docx:
        try:
            document = docx.Document(io.BytesIO(data))
            return "\n".join([p.text for p in document.paragraphs])
        except Exception:
            pass

    # Fallback: treat as text
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return data.decode(errors="replace")


def simple_proposal_generator(text: str) -> dict:
    """
    Heuristic-based generator that creates a structured proposal
    from RFP plain text. This avoids heavy LLM dependencies.
    """
    import re

    # Try to detect some fields
    title = None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines:
        title = lines[0][:120]

    # Naive client and project extraction
    client = None
    project = None
    due_date = None

    # Client detection
    client_patterns = [
        r"(?:client|agency|organization|company)[:\s]+(.{2,80})",
        r"\bfor\s+(?:the\s+)?([A-Z][\w&\-\s]{2,60})",
    ]
    joined = "\n".join(lines)
    for pat in client_patterns:
        m = re.search(pat, joined, flags=re.IGNORECASE)
        if m:
            client = m.group(1).strip().strip(".:,;-")
            break

    # Project name detection
    proj_patterns = [
        r"(?:project|rfp title|subject)[:\s]+(.{2,120})",
    ]
    for pat in proj_patterns:
        m = re.search(pat, joined, flags=re.IGNORECASE)
        if m:
            project = m.group(1).strip().strip(".:,;-")
            break

    # Due date detection
    date_patterns = [
        r"due\s+date[:\s]+([A-Za-z0-9,\-/ ]{4,40})",
        r"proposals?\s+due[:\s]+([A-Za-z0-9,\-/ ]{4,40})",
    ]
    for pat in date_patterns:
        m = re.search(pat, joined, flags=re.IGNORECASE)
        if m:
            dd = m.group(1).strip()
            due_date = dd
            break

    # Build sections heuristically
    sections = []
    # Executive Summary
    summary = (
        f"This proposal responds to the RFP{' for ' + client if client else ''}. "
        f"It outlines our understanding, approach, timeline, and pricing to deliver"
        f" the {project or 'requested solution'}."
    )

    # Understanding of Needs
    needs_excerpt = " ".join(lines[:20])[:800]

    sections.append({
        "heading": "Executive Summary",
        "content": summary,
    })
    sections.append({
        "heading": "Understanding of Requirements",
        "content": needs_excerpt or "We have carefully reviewed the RFP and understand the objectives and constraints.",
    })
    sections.append({
        "heading": "Approach & Methodology",
        "content": "We will follow a phased approach: discovery, design, implementation, testing, and deployment, ensuring quality and transparency throughout.",
    })
    sections.append({
        "heading": "Project Team",
        "content": "Our experienced cross-functional team will lead strategy, design, engineering, QA, and project management.",
    })
    sections.append({
        "heading": "Timeline",
        "content": "A detailed timeline will be finalized upon kickoff; typical delivery occurs in 8-12 weeks depending on scope.",
    })
    sections.append({
        "heading": "Pricing",
        "content": "Pricing is based on scope and effort; a fixed bid or time-and-materials model can be provided upon clarification of requirements.",
    })

    title_out = project or title or "Proposal"

    return {
        "title": title_out,
        "summary": summary,
        "client_name": client,
        "project_name": project,
        "due_date": due_date,
        "sections": sections,
    }


@app.get("/")
async def root():
    return {"message": "RFP → Proposal API running"}


# -----------------
# RFP Upload → Basic Proposal (existing flow)
# -----------------
@app.post("/api/rfps/upload", response_model=ProposalResponse)
async def upload_rfp(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    content = extract_text_from_file(file, data)

    # Store RFP
    rfp = Rfp(
        filename=file.filename or "rfp",
        content=content,
        filesize=len(data),
        mimetype=file.content_type or None,
    )
    rfp_id = create_document("rfp", rfp)

    # Generate proposal
    proposal_dict = simple_proposal_generator(content)
    prop = Proposal(
        rfp_id=rfp_id,
        title=proposal_dict["title"],
        summary=proposal_dict["summary"],
        client_name=proposal_dict.get("client_name"),
        project_name=proposal_dict.get("project_name"),
        due_date=proposal_dict.get("due_date"),
        sections=proposal_dict["sections"],
        status="generated",
        generated_at=datetime.now(timezone.utc),
    )
    proposal_id = create_document("proposal", prop)

    return ProposalResponse(proposal_id=proposal_id, rfp_id=rfp_id)


@app.get("/api/proposals/{proposal_id}")
async def get_proposal(proposal_id: str):
    from bson import ObjectId

    try:
        obj_id = ObjectId(proposal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid proposal id")

    doc = db["proposal"].find_one({"_id": obj_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Proposal not found")

    # Convert ObjectId
    doc["id"] = str(doc.pop("_id"))
    return doc


@app.get("/api/rfps")
async def list_rfps(limit: int = 50):
    rfps = get_documents("rfp", {}, limit)
    # normalize
    out = []
    for d in rfps:
        d_out = {
            "id": str(d.get("_id")),
            "filename": d.get("filename"),
            "filesize": d.get("filesize"),
            "mimetype": d.get("mimetype"),
        }
        out.append(d_out)
    return out


# -----------------
# Collections: Team Members & Project Highlights
# -----------------
class CreateTeamMember(BaseModel):
    name: str
    role: str
    titleQual: Optional[str] = None
    blurb: Optional[str] = None
    bullets: Optional[str] = None  # multiline
    photo_url: Optional[str] = None


@app.post("/api/team-members")
async def create_team_member(payload: CreateTeamMember):
    tm = TeamMember(**payload.model_dump())
    _id = create_document("teammember", tm)
    return {"id": _id}


@app.get("/api/team-members")
async def list_team_members(limit: int = 100):
    docs = get_documents("teammember", {}, limit)
    out = []
    for d in docs:
        out.append({
            "id": str(d.get("_id")),
            "name": d.get("name"),
            "role": d.get("role"),
            "titleQual": d.get("titleQual"),
            "blurb": d.get("blurb"),
            "bullets": d.get("bullets"),
            "photo_url": d.get("photo_url") or TRANSPARENT_PNG_DATA_URL,
        })
    return out


class CreateProjectHighlight(BaseModel):
    title: str
    sector: Optional[str] = None
    summary: Optional[str] = None
    bullets: Optional[str] = None


@app.post("/api/project-highlights")
async def create_project_highlight(payload: CreateProjectHighlight):
    ph = ProjectHighlight(**payload.model_dump())
    _id = create_document("projecthighlight", ph)
    return {"id": _id}


@app.get("/api/project-highlights")
async def list_project_highlights(limit: int = 100):
    docs = get_documents("projecthighlight", {}, limit)
    out = []
    for d in docs:
        out.append({
            "id": str(d.get("_id")),
            "title": d.get("title"),
            "sector": d.get("sector"),
            "summary": d.get("summary"),
            "bullets": d.get("bullets"),
        })
    return out


# -----------------
# Rich ProposalDocs (placeholders, files, versions)
# -----------------
class CreateProposalDoc(BaseModel):
    clientName: str
    projectTitle: str
    rfpId: Optional[str] = None
    placeholdersJson: Any
    teamMemberIds: List[str] = []
    projectHighlightIds: List[str] = []
    status: Optional[str] = "draft"


@app.post("/api/proposals-docs")
async def create_proposal_doc(payload: CreateProposalDoc):
    doc = ProposalDoc(
        clientName=payload.clientName or "Client",
        projectTitle=payload.projectTitle or "Project",
        rfpId=payload.rfpId,
        placeholdersJson=payload.placeholdersJson or {},
        status=payload.status or "draft",
        version=1,
        teamMemberIds=payload.teamMemberIds or [],
        projectHighlightIds=payload.projectHighlightIds or [],
    )
    _id = create_document("proposaldoc", doc)
    return {"id": _id, "version": 1}


@app.get("/api/proposals-docs")
async def list_proposal_docs(limit: int = 100):
    docs = get_documents("proposaldoc", {}, limit)
    out = []
    for d in docs:
        out.append({
            "id": str(d.get("_id")),
            "clientName": d.get("clientName"),
            "projectTitle": d.get("projectTitle"),
            "version": d.get("version", 1),
            "status": d.get("status", "draft"),
            "created_at": d.get("created_at"),
        })
    # Sort by created_at desc if present
    out.sort(key=lambda x: x.get("created_at") or datetime(1970,1,1,tzinfo=timezone.utc), reverse=True)
    return out


@app.get("/api/proposals-docs/{doc_id}")
async def get_proposal_doc(doc_id: str):
    from bson import ObjectId
    try:
        obj_id = ObjectId(doc_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    d = db["proposaldoc"].find_one({"_id": obj_id})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    d["id"] = str(d.pop("_id"))
    return d


class RegeneratePayload(BaseModel):
    placeholdersJson: Any
    status: Optional[str] = "draft"


@app.post("/api/proposals-docs/{doc_id}/regenerate")
async def regenerate_proposal_doc(doc_id: str, payload: RegeneratePayload):
    from bson import ObjectId
    try:
        obj_id = ObjectId(doc_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    current = db["proposaldoc"].find_one({"_id": obj_id})
    if not current:
        raise HTTPException(status_code=404, detail="Not found")

    # Duplicate with version+1
    new_doc = current.copy()
    new_doc.pop("_id", None)
    new_doc["version"] = int(current.get("version", 1)) + 1
    new_doc["placeholdersJson"] = payload.placeholdersJson or {}
    new_doc["status"] = payload.status or "draft"
    new_doc["created_at"] = datetime.now(timezone.utc)
    new_doc["updated_at"] = datetime.now(timezone.utc)

    res = db["proposaldoc"].insert_one(new_doc)
    return {"id": str(res.inserted_id), "version": new_doc["version"]}


# -----------------
# Utility & Health
# -----------------
@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, "name") else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
