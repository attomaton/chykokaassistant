"""Vercel Python entrypoint: exposes the FastAPI ASGI app.

vercel.json rewrites every path to this file; FastAPI's own routing (in
app.py) handles /, /health, and /api/telegram/webhook internally.
"""
from app import app

__all__ = ["app"]
