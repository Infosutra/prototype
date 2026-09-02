from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.audio import (
    AudioRecordingOut,
    AudioRecordingSummary,
    AudioRecordingUpdate,
    SpeakerLabelsUpdate,
    TranscribeRequest,
)
from app.schemas.common import OkResponse, StudyIdQuery
from app.services import audio as audio_service
from app.services import studies as studies_service
from app.services.audio_storage import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_EXTENSIONS,
    playback_media_type,
    playback_response_headers,
    resolve_recording_file,
)
from app.services.transcript_export import get_or_build_docx, get_or_build_pdf
from app.services.transcript_segments import normalize_segment_layout
from app.services.transcription_job import process_recording_transcription, queue_transcription

router = APIRouter(prefix="/audio", tags=["audio"])


def _validate_upload(filename: str, content_type: str) -> None:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if content_type not in ALLOWED_CONTENT_TYPES and suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported audio format. Use mp3, wav, m4a, ogg, webm, or flac.",
        )


@router.get("", response_model=list[AudioRecordingSummary], operation_id="getAudioRecordings")
def list_audio_recordings(
    q: StudyIdQuery = Depends(),
    db: Session = Depends(get_db),
) -> list[AudioRecordingSummary]:
    if not q.study_id:
        raise HTTPException(status_code=400, detail="studyId is required")
    study = studies_service.get_study(db, q.study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return audio_service.list_recordings(db, q.study_id)


@router.post("", response_model=AudioRecordingOut, operation_id="createAudioRecording")
async def create_audio_recording(
    study_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> AudioRecordingOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if not name.strip():
        raise HTTPException(status_code=400, detail="name is required")

    filename = file.filename or "recording.mp3"
    content_type = file.content_type or "application/octet-stream"
    _validate_upload(filename, content_type)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        row = audio_service.create_recording(
            db,
            study_id=study_id,
            name=name,
            description=description,
            filename=filename,
            content_type=content_type,
            data=data,
        )
    except audio_service.DuplicateRecordingNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return audio_service.to_out(db, row)


@router.get("/{recording_id}", response_model=AudioRecordingOut, operation_id="getAudioRecording")
def get_audio_recording(
    recording_id: str,
    segment_layout: str = Query(default="linear", alias="segmentLayout", pattern="^(linear|provider)$"),
    db: Session = Depends(get_db),
) -> AudioRecordingOut:
    row = audio_service.get_recording(db, recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    return audio_service.to_out(db, row, segment_layout=normalize_segment_layout(segment_layout))


@router.patch(
    "/{recording_id}",
    response_model=AudioRecordingOut,
    operation_id="updateAudioRecording",
)
def update_audio_recording(
    recording_id: str,
    payload: AudioRecordingUpdate,
    db: Session = Depends(get_db),
) -> AudioRecordingOut:
    row = audio_service.get_recording(db, recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    try:
        row = audio_service.update_recording(
            db,
            row,
            name=payload.name,
            description=payload.description,
        )
    except audio_service.DuplicateRecordingNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return audio_service.to_out(db, row)


@router.patch(
    "/{recording_id}/speaker-labels",
    response_model=AudioRecordingOut,
    operation_id="updateAudioRecordingSpeakerLabels",
)
def update_audio_recording_speaker_labels(
    recording_id: str,
    payload: SpeakerLabelsUpdate,
    db: Session = Depends(get_db),
) -> AudioRecordingOut:
    row = audio_service.get_recording(db, recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    row = audio_service.update_speaker_labels(db, row, payload.labels)
    return audio_service.to_out(db, row)


@router.delete("/{recording_id}", response_model=OkResponse, operation_id="deleteAudioRecording")
def delete_audio_recording(
    recording_id: str,
    db: Session = Depends(get_db),
) -> OkResponse:
    row = audio_service.get_recording(db, recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    audio_service.delete_recording(db, row)
    return OkResponse()


def _resolve_recording_source(row):
    try:
        path = resolve_recording_file(
            row.storage_path,
            storage_folder=row.storage_folder,
            original_filename=row.original_filename,
            content_type=row.content_type,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Audio file is missing on the server. Sync data/audio/ to this device.",
        ) from None
    media_type = playback_media_type(row.content_type, row.original_filename or "")
    return path, media_type


@router.head("/{recording_id}/file", include_in_schema=False)
def head_audio_recording_file(
    recording_id: str,
    db: Session = Depends(get_db),
):
    row = audio_service.get_recording(db, recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    path, media_type = _resolve_recording_source(row)
    stat = path.stat()
    return Response(
        headers=playback_response_headers(
            content_length=stat.st_size,
            content_type=media_type,
        )
    )


@router.get(
    "/{recording_id}/file",
    response_model=None,
    operation_id="getAudioRecordingFile",
    responses={200: {"content": {"audio/*": {}}}, 206: {"content": {"audio/*": {}}}},
)
def get_audio_recording_file(
    recording_id: str,
    db: Session = Depends(get_db),
):
    row = audio_service.get_recording(db, recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    path, media_type = _resolve_recording_source(row)
    return FileResponse(
        path,
        media_type=media_type,
        headers=playback_response_headers(),
    )


def _safe_export_filename(name: str, extension: str) -> str:
    safe = name.replace("/", "-")[:80]
    ascii_name = safe.encode("ascii", "replace").decode("ascii").replace("?", "-").strip()
    return f"{ascii_name or 'transcript'}.{extension}"


@router.get(
    "/{recording_id}/download",
    response_model=None,
    operation_id="downloadAudioRecordingTranscript",
    responses={
        200: {
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
            }
        }
    },
)
def download_audio_recording_transcript(
    recording_id: str,
    format: str = Query(default="pdf", pattern="^(pdf|docx)$"),
    segment_layout: str = Query(default="linear", alias="segmentLayout", pattern="^(linear|provider)$"),
    db: Session = Depends(get_db),
):
    row = audio_service.get_recording(db, recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    if row.transcription_status != "succeeded":
        raise HTTPException(status_code=400, detail="Transcript is not available yet")

    layout = normalize_segment_layout(segment_layout)
    filename = _safe_export_filename(row.name, format)
    try:
        if format == "pdf":
            content = get_or_build_pdf(db, row, segment_layout=layout)
            media_type = "application/pdf"
        else:
            content = get_or_build_docx(db, row, segment_layout=layout)
            media_type = (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface generation failures cleanly
        raise HTTPException(status_code=500, detail=f"Failed to build export: {exc}") from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{recording_id}/transcribe",
    response_model=AudioRecordingOut,
    operation_id="transcribeAudioRecording",
    responses={400: {"description": "Bad request"}},
)
def transcribe_audio_recording(
    recording_id: str,
    payload: TranscribeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AudioRecordingOut:
    row = audio_service.get_recording(db, recording_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")
    if row.transcription_status in {"queued", "running"}:
        raise HTTPException(status_code=400, detail="Transcription already in progress")
    try:
        row = queue_transcription(db, row, language_code=payload.language_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(process_recording_transcription, row.id)
    return audio_service.to_out(db, row)
