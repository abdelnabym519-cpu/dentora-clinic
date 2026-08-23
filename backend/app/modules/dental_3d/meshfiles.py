"""Mesh file validation — pure domain rules, no framework imports.

Phase 2 accepts exactly two container formats (STL, OBJ) — the minimum
safe surface. Everything here is deliberately stdlib-only so the rules
are unit-testable in isolation and reusable by any future adapter
(upload today, batch import later). The constants double as the
discovery vocabulary for the intraoral-scan geometry source: only
documents stored with a canonical mesh MIME are ever surfaced in a
scene.

Security posture (never trust client metadata): a file is accepted
only when **extension, declared MIME and actual byte content** all
agree. Content is sniffed — binary STL must match the exact
``84 + 50·triangle_count`` length, ASCII STL must start with
``solid`` and contain ``facet``, OBJ must decode as text with both
``v`` and ``f`` records.
"""

from __future__ import annotations

from uuid import UUID

#: Accepted container formats (Phase 2 scope — do not extend casually).
SUPPORTED_MESH_FORMATS: frozenset[str] = frozenset({"stl", "obj"})

#: Extension → format.
_FORMAT_BY_EXTENSION: dict[str, str] = {"stl": "stl", "obj": "obj"}

#: Canonical MIME stored on the media document (also the discovery set).
CANONICAL_MIME_BY_FORMAT: dict[str, str] = {
    "stl": "model/stl",
    "obj": "model/obj",
}

#: MIME types a browser may legitimately declare for each format.
#: ``application/octet-stream`` is accepted because most browsers do
#: not map ``.stl`` / ``.obj`` to a specific type. The document is
#: always stored with the canonical MIME regardless of declaration.
ACCEPTED_MIME_BY_FORMAT: dict[str, frozenset[str]] = {
    "stl": frozenset({"model/stl", "application/sla", "application/octet-stream"}),
    "obj": frozenset({"model/obj", "text/x-obj", "text/plain", "application/octet-stream"}),
}

#: How much of the file the sniffers look at (validation only).
_SNIFF_WINDOW = 64 * 1024


class MeshUploadError(ValueError):
    """Raised when a mesh upload fails validation.

    The message is safe to return to the client (no byte data echoed).
    """

    @property
    def code(self) -> str:
        """Stable machine-readable reason (first token before ':')."""
        return str(self).split(":", 1)[0].strip()


def mesh_mimes() -> frozenset[str]:
    """Canonical MIME types that identify a mesh document."""
    return frozenset(CANONICAL_MIME_BY_FORMAT.values())


def canonical_mime(mesh_format: str) -> str:
    try:
        return CANONICAL_MIME_BY_FORMAT[mesh_format]
    except KeyError as exc:
        raise MeshUploadError(f"unsupported_format: {mesh_format}") from exc


def format_for_mime(mime_type: str) -> str | None:
    """Inverse of :func:`canonical_mime` (discovery helper); ``None`` if not a mesh."""
    for fmt, mime in CANONICAL_MIME_BY_FORMAT.items():
        if mime == mime_type:
            return fmt
    return None


def mesh_download_url(document_id: UUID) -> str:
    """Stable public URL of a mesh document's content.

    Mirrors the media module's own download route (its URL helpers are
    module-private). The path is media's documented public contract;
    scene payloads embed it so viewers never hardcode route shapes.
    """
    return f"/api/v1/media/documents/{document_id}/download"


def detect_mesh_format(filename: str, content_type: str | None, data: bytes) -> str:
    """Validate extension + MIME + content and return the format.

    Raises :class:`MeshUploadError` with a stable code prefix
    (``unsupported_extension`` / ``mime_mismatch`` / ``empty_file`` /
    ``malformed_stl`` / ``malformed_obj``).
    """
    if not data:
        raise MeshUploadError("empty_file: no content received")

    extension = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    mesh_format = _FORMAT_BY_EXTENSION.get(extension)
    if mesh_format is None:
        raise MeshUploadError(
            f"unsupported_extension: .{extension or '(none)'} — supported: .stl, .obj"
        )

    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if declared and declared not in ACCEPTED_MIME_BY_FORMAT[mesh_format]:
        raise MeshUploadError(
            f"mime_mismatch: '{declared}' does not match .{extension} "
            f"(expected one of: {', '.join(sorted(ACCEPTED_MIME_BY_FORMAT[mesh_format]))})"
        )

    if mesh_format == "stl":
        _sniff_stl(data)
    else:
        _sniff_obj(data)
    return mesh_format


def _sniff_stl(data: bytes) -> None:
    """Binary STL is exactly 84 + 50·n bytes; ASCII STL starts 'solid'."""
    if len(data) >= 84:
        triangles = int.from_bytes(data[80:84], "little")
        if len(data) == 84 + 50 * triangles:
            return
    window = data[:_SNIFF_WINDOW].lstrip().lower()
    if window.startswith(b"solid") and b"facet" in window:
        return
    raise MeshUploadError("malformed_stl: content is not a valid STL file")


def _sniff_obj(data: bytes) -> None:
    """OBJ is text containing at least one vertex and one face record."""
    try:
        window = data[:_SNIFF_WINDOW].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MeshUploadError("malformed_obj: content is not text") from exc

    has_vertex = False
    has_face = False
    for line in window.splitlines():
        stripped = line.strip()
        if stripped.startswith("v ") or stripped == "v":
            has_vertex = True
        elif stripped.startswith("f ") or stripped == "f":
            has_face = True
        if has_vertex and has_face:
            return
    raise MeshUploadError("malformed_obj: no vertex/face records found")
