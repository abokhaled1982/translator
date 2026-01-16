"""
Simple webhook server to receive LiveKit egress completion events
and trigger transcript processing.

Run with: uvicorn src.webhook_server:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging

from fastapi import FastAPI, Request
from dotenv import load_dotenv

from src.process_recording import handle_egress_webhook

load_dotenv(".env.local")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook-server")

app = FastAPI(title="LiveKit Egress Webhook Handler")


@app.post("/egress-webhook")
async def egress_webhook(request: Request):
    """Handle LiveKit egress webhooks."""
    try:
        webhook_data = await request.json()
        logger.info(f"Received webhook: {webhook_data.get('event')}")
        
        # Process in background to return quickly
        asyncio.create_task(handle_egress_webhook(webhook_data))
        
        return {"status": "ok"}
    
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
