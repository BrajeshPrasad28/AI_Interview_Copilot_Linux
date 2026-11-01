import io
import qrcode
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core.state import (
    TEMPLATES_DIR,
    LOCAL_IP,
    PORT,
    current_state,
    ai_engine,
    get_auth_token_from_request,
    is_valid_token,
    get_pairing_token,
    get_mobile_url,
)

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@router.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    """Pairing / Welcome Dashboard with QR Code."""
    current_token = get_pairing_token()
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "mobile_url": get_mobile_url(),
            "local_ip": LOCAL_IP,
            "port": PORT,
            "mode": current_state["mode"],
            "language": current_state["language"],
            "has_api_key": bool(ai_engine.api_key or ai_engine.groq_api_key),
            "has_gemini_key": bool(ai_engine.api_key),
            "has_groq_key": bool(ai_engine.groq_api_key),
            "pairing_token": current_token
        }
    )
    response.set_cookie(key="pairing_token", value=current_token, max_age=86400 * 30, samesite="lax")
    return response

@router.get("/mobile", response_class=HTMLResponse)
async def mobile_page(request: Request):
    """Mobile Companion Interface for Phone / Second Device."""
    client_host = request.client.host if request.client else ""
    is_localhost = client_host in ("127.0.0.1", "::1", "localhost", "testclient")
    token = get_auth_token_from_request(request)
    if not (is_valid_token(token) or is_localhost):
        return HTMLResponse(
            content="""
            <div style="font-family:sans-serif;max-width:400px;margin:50px auto;padding:24px;border-radius:16px;background:#0f172a;color:#f8fafc;text-align:center;">
                <h2 style="color:#ef4444;margin-bottom:12px;">🔒 Pairing Token Required</h2>
                <p style="color:#94a3b8;font-size:0.95rem;line-height:1.6;">
                    Please scan the QR code on your PC dashboard using your mobile phone camera to securely pair this device.
                </p>
            </div>
            """,
            status_code=401
        )

    current_token = get_pairing_token()
    response = templates.TemplateResponse(
        request=request,
        name="mobile.html",
        context={
            "local_ip": LOCAL_IP,
            "port": PORT,
            "mode": current_state["mode"],
            "language": current_state["language"],
            "has_api_key": bool(ai_engine.api_key or ai_engine.groq_api_key),
            "has_gemini_key": bool(ai_engine.api_key),
            "has_groq_key": bool(ai_engine.groq_api_key),
            "pairing_token": current_token
        }
    )
    response.set_cookie(key="pairing_token", value=current_token, max_age=86400 * 30, samesite="lax")
    return response

@router.get("/overlay", response_class=HTMLResponse)
async def overlay_page(request: Request):
    """Transparent Desktop Overlay for standard Zoom / Meet calls."""
    client_host = request.client.host if request.client else ""
    is_localhost = client_host in ("127.0.0.1", "::1", "localhost", "testclient")
    token = get_auth_token_from_request(request)
    if not (is_valid_token(token) or is_localhost):
        return HTMLResponse(
            content="<h2>🔒 Unauthorized Access</h2><p>Pairing token required.</p>",
            status_code=401
        )

    current_token = get_pairing_token()
    response = templates.TemplateResponse(
        request=request,
        name="overlay.html",
        context={
            "mode": current_state["mode"],
            "language": current_state["language"],
            "pairing_token": current_token
        }
    )
    response.set_cookie(key="pairing_token", value=current_token, max_age=86400 * 30, samesite="lax")
    return response

@router.get("/qr")
async def get_qr_code(request: Request):
    """Returns a PNG QR code of the mobile companion URL (including token) for instant phone pairing."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(get_mobile_url())
    qr.make(fit=True)
    img = qr.make_image(fill_color="#10b981", back_color="#0f172a")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")
