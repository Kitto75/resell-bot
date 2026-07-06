from __future__ import annotations

import tempfile
from pathlib import Path


def make_subscription_qr_png(data: str, username: str = "subscription") -> Path:
    """Generate a high-error-correction PNG QR code in a temporary file."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_H

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=12,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    safe_username = "".join(ch for ch in username if ch.isalnum() or ch in {"_", "-"}) or "subscription"
    with tempfile.NamedTemporaryFile(prefix=f"{safe_username}-", suffix=".png", delete=False) as tmp:
        path = Path(tmp.name)
    image.save(path, format="PNG")
    return path
