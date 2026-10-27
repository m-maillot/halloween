"""Images des composants : téléversement (validé, redimensionné, réencodé) et service."""

import asyncio
import hashlib
import io
import os
import re
import tempfile
import warnings
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

from halloween.api.deps import EngineDep
from halloween.api.errors import api_error

router = APIRouter(tags=["images"])  # protégé par le jeton
public_router = APIRouter(tags=["images"])  # lecture publique (balises <img>, sans en-tête)

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 25_000_000  # garde-fou contre les « bombes de décompression »
MAX_SIDE = 512
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(png|jpe?g|webp)$")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


class ImageOut(BaseModel):
    image: str  # à placer dans le champ `image` d'un composant
    url: str
    width: int
    height: int


class ImageRejected(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def process_image(data: bytes) -> tuple[bytes, int, int]:
    """Valide l'image, la fait pivoter selon l'EXIF, la réduit à 512 px et la réencode en WebP.

    Le réencodage supprime les métadonnées (EXIF, position GPS) et tout contenu parasite.
    """
    try:
        with warnings.catch_warnings():
            # Pillow prévient dès 89 Mpx ; notre propre limite (25 Mpx) est plus stricte.
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
        if image.format not in ("PNG", "JPEG", "WEBP"):
            raise ImageRejected("format non pris en charge (PNG, JPEG ou WebP)")
        if image.width * image.height > MAX_PIXELS:
            raise ImageRejected("image trop grande (plus de 25 mégapixels)", 413)
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageRejected("fichier image illisible") from exc
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA") or "transparency" in image.info
    image = image.convert("RGBA" if has_alpha else "RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="WEBP", quality=85, method=4)
    return out.getvalue(), image.width, image.height


def save_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@router.post(
    "/images",
    response_model=ImageOut,
    status_code=201,
    operation_id="upload_image",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                kind: {"schema": {"type": "string", "format": "binary"}} for kind in ALLOWED_TYPES
            },
        }
    },
    responses={
        413: {"description": "Image trop lourde (5 Mo) ou trop grande"},
        415: {"description": "Type de contenu non pris en charge"},
        422: {"description": "Image illisible"},
    },
)
async def upload_image(request: Request, engine: EngineDep) -> ImageOut:
    """Téléverse une image (corps brut, `Content-Type: image/png|jpeg|webp`, 5 Mo maximum)."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_TYPES:
        raise api_error(415, "Content-Type attendu : image/png, image/jpeg ou image/webp")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise api_error(413, "image trop lourde (5 Mo maximum)")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise api_error(413, "image trop lourde (5 Mo maximum)")
        chunks.append(chunk)
    try:
        data, width, height = await asyncio.to_thread(process_image, b"".join(chunks))
    except ImageRejected as exc:
        raise api_error(exc.status, str(exc)) from exc
    name = hashlib.sha256(data).hexdigest()[:16] + ".webp"
    await asyncio.to_thread(save_bytes, engine.images_dir / name, data)
    return ImageOut(image=name, url=f"/api/images/{name}", width=width, height=height)


@public_router.get(
    "/images/{filename}",
    response_class=FileResponse,
    operation_id="get_image",
    responses={404: {"description": "Image inconnue"}},
)
async def get_image(filename: str, request: Request) -> FileResponse:
    """Sert une image téléversée (nom = empreinte du contenu, donc cache illimité)."""
    if not FILENAME.match(filename):
        raise api_error(404, "image inconnue")
    path = request.app.state.engine.images_dir / filename
    if not path.is_file():
        raise api_error(404, "image inconnue")
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[filename.rsplit(".", 1)[1].lower()],
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
