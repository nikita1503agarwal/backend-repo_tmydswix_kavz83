import os
import io
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from database import db, create_document, get_documents
from schemas import Rfp, Proposal

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
