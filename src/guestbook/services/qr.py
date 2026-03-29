"""QR code generation service."""

import io

import qrcode
from qrcode.image.pil import PilImage


def generate_qr_png(url: str, size: int = 10) -> bytes:
    """Generate a QR code PNG for the given URL.

    Args:
        url: The URL to encode.
        size: Box size in pixels (each module). Default 10.

    Returns:
        PNG image bytes.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=size,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img: PilImage = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
