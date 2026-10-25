import io, warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException
from .models import Attachment, uid
from .config import settings
from .extensions.storage import LocalImageStorage

Image.MAX_IMAGE_PIXELS = 20_000_000


def save_image(db, data, customer_id, session_id=None):
    if len(data) > settings().max_upload_bytes:
        raise HTTPException(413, "图片不能超过 5MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ("JPEG", "PNG", "WEBP"):
                    raise ValueError()
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                output = io.BytesIO()
                image.save(output, "JPEG", quality=88)
    except (
        UnidentifiedImageError,
        ValueError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(
            422, "仅支持有效的 JPEG、PNG、WebP 图片（不超过 2000 万像素）"
        )
    ident = uid()
    path = LocalImageStorage(settings().upload_dir).put(
        f"{ident}.jpg", output.getvalue()
    )
    a = Attachment(
        id=ident,
        customer_id=customer_id,
        visitor_session_id=session_id,
        path=str(path),
        mime="image/jpeg",
    )
    db.add(a)
    db.flush()
    return a
