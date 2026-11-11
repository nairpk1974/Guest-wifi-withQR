import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal
from .routers import admin, auth, guests, portal, radius, reports

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = get_settings()

app = FastAPI(title="Bessel Systems Guest Wi-Fi", version="1.0.0",
              docs_url="/api/docs" if settings.environment == "development" else None,
              redoc_url=None, openapi_url="/api/openapi.json" if settings.environment == "development" else None)

app.include_router(auth.router)
app.include_router(guests.router)
app.include_router(reports.router)
app.include_router(admin.router)
app.include_router(radius.router)
app.include_router(portal.router)
app.mount("/static/guest", StaticFiles(directory=str(Path(__file__).parent / "static" / "guest")), name="guest-static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errs = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg", "")} for e in exc.errors()]
    return JSONResponse({"detail": "Validation failed", "errors": errs}, status_code=422)


@app.get("/api/health")
def health():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "degraded", "database": "down"}, status_code=503)
    finally:
        db.close()
