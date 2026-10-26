"""UC02 endpoints: customer upload, and the staff document queue."""
import asyncio
import time
import uuid

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.files.base import ContentFile
from django.http import FileResponse, JsonResponse
from ninja import Router, Schema
from ninja.errors import HttpError

from chat import events
from chat.api import get_session
from chat.models import Message, new_reference
from core.security import current_staff, display_name, rate_limit

from .models import Document
from .processing import DocumentRejected, check_size, process

router = Router(tags=["documents"])
staff_router = Router(tags=["staff"])


def _reject(code: str, message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "code": code, "detail": message}, status=status)


def _doc_row(d: Document) -> dict:
    return {
        "id": str(d.id),
        "reference": d.reference,
        "name": d.original_name,
        "file_type": d.file_type,
        "size_bytes": d.size_bytes,
        "page_count": d.page_count,
        "word_count": d.word_count,
        "has_text_layer": d.has_text_layer,
        "category": d.category,
        "department": d.department,
        "routing_reason": d.routing_reason,
        "status": d.status,
        "session_id": str(d.session_id) if d.session_id else None,
        "processing_ms": d.processing_ms,
        "created_at": d.created_at.isoformat(),
    }


@router.post("/sessions/{session_id}/documents")
async def upload(request, session_id: uuid.UUID):
    """Multipart field `file`. Returns an acknowledgement with a case reference, or a clear error."""
    started = time.perf_counter()
    session = await get_session(request, session_id)
    await rate_limit(f"doc:{session.id}", limit=10)

    # Reject oversized uploads from the declared length before touching the body.
    declared = int(request.META.get("CONTENT_LENGTH") or 0)
    if declared > settings.AUBOT["MAX_UPLOAD_BYTES"] + 64 * 1024:
        limit_mb = settings.AUBOT["MAX_UPLOAD_BYTES"] // (1024 * 1024)
        return _reject("too_large", f"The file is larger than the {limit_mb} MB limit; please compress or split it.", 413)

    upload_file = request.FILES.get("file")
    if upload_file is None:
        return _reject("missing_file", "No file was received. Please choose a PDF or Word document.")
    try:
        check_size(upload_file.size)
        data = upload_file.read()
        parsed = await asyncio.to_thread(process, upload_file.name, data)  # CPU-bound parsing off the event loop
    except DocumentRejected as exc:
        return _reject(exc.code, exc.message, 413 if exc.code == "too_large" else 400)

    doc = Document(
        reference=new_reference("DOC"),
        session=session,
        original_name=upload_file.name[:255],
        file_type=parsed.file_type,
        size_bytes=parsed.size_bytes,
        sha256=parsed.sha256,
        page_count=parsed.page_count,
        word_count=parsed.word_count,
        has_text_layer=parsed.has_text_layer,
        text_excerpt=parsed.text[:2000],
        category=parsed.category,
        department=parsed.department,
        routing_reason=parsed.routing_reason,
    )
    await asyncio.to_thread(doc.file.save, f"upload.{parsed.file_type}", ContentFile(data), False)
    doc.processing_ms = int((time.perf_counter() - started) * 1000)
    await doc.asave()

    note = "" if parsed.has_text_layer else " It looks like a scanned image, so a team member will review it manually."
    ack = await Message.objects.acreate(
        session=session,
        role=Message.SYSTEM,
        source="document",
        text=(
            f"Thanks, we've received \"{doc.original_name}\". Your reference is {doc.reference}, "
            f"and it has been sent to our {doc.department} team.{note}"
        ),
    )
    await events.to_staff("document.new", _doc_row(doc))
    await events.to_staff("message.new", {"session_id": str(session.id), "message": ack.as_dict()})
    return {"ok": True, "document": _doc_row(doc), "message": ack.as_dict()}


class DocumentUpdateIn(Schema):
    status: str


@staff_router.get("/documents")
async def list_documents(request, status: str = "", department: str = ""):
    await current_staff(request)
    qs = Document.objects.all()
    if status:
        qs = qs.filter(status=status)
    if department:
        qs = qs.filter(department=department)
    return {"items": [_doc_row(d) async for d in qs[:300]]}


@staff_router.get("/documents/{doc_id}")
async def document_detail(request, doc_id: uuid.UUID):
    await current_staff(request)
    doc = await Document.objects.filter(id=doc_id).afirst()
    if doc is None:
        raise HttpError(404, "Document not found.")
    return {**_doc_row(doc), "text_excerpt": doc.text_excerpt}


@staff_router.patch("/documents/{doc_id}")
async def update_document(request, doc_id: uuid.UUID, payload: DocumentUpdateIn):
    user = await current_staff(request)
    if payload.status not in dict(Document.STATUSES):
        raise HttpError(400, "Unknown status.")
    doc = await Document.objects.filter(id=doc_id).afirst()
    if doc is None:
        raise HttpError(404, "Document not found.")
    doc.status = payload.status
    doc.processed_by = user if payload.status == Document.PROCESSED else doc.processed_by
    await doc.asave(update_fields=["status", "processed_by"])
    row = _doc_row(doc)
    await events.to_staff("document.updated", {**row, "by": display_name(user)})
    return row


@staff_router.get("/documents/{doc_id}/download")
async def download(request, doc_id: uuid.UUID):
    """Staff-only download; uploaded files are never publicly routable."""
    await current_staff(request)
    doc = await Document.objects.filter(id=doc_id).afirst()
    if doc is None:
        raise HttpError(404, "Document not found.")
    handle = await sync_to_async(doc.file.open)("rb")
    return FileResponse(handle, as_attachment=True, filename=doc.original_name)
