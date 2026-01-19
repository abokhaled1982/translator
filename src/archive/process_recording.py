"""
Process recorded call audio and generate transcripts using STT.

This script can be triggered by:
1. LiveKit egress webhook (when recording completes)
2. Manual execution for testing
3. Scheduled job to process pending recordings
"""

import asyncio
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

logger = logging.getLogger("recording-processor")
logging.basicConfig(level=logging.INFO)

load_dotenv(".env.local")

# Configuration (Supabase Storage)
S3_BUCKET = os.getenv("S3_BUCKET", "")  # Your Supabase bucket name
S3_REGION = os.getenv("S3_REGION", "eu-central-1")
S3_ACCESS_KEY = os.getenv("ACCESS_SUPABASE", "")
S3_SECRET_KEY = os.getenv("SECRET_SUPABASE", "")
S3_ENDPOINT = os.getenv("ENDPOINT_SUPABASE", "https://rexdoyxjqixzchgaadum.storage.supabase.co/storage/v1/s3")

# STT provider (choose one)
STT_PROVIDER = os.getenv("STT_PROVIDER", "openai")  # "openai", "google", "deepgram"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

# Webhook to send transcript to
TRANSCRIPT_WEBHOOK_URL = os.getenv("TRANSCRIPT_WEBHOOK_URL", "")


async def download_from_s3(s3_path: str, local_path: Path) -> bool:
    """Download audio file from Supabase Storage (S3-compatible)."""
    try:
        import boto3
        
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION,
            endpoint_url=S3_ENDPOINT,  # Supabase endpoint
        )
        
        # Extract bucket and key from s3://bucket/path
        bucket = S3_BUCKET
        key = s3_path.replace(f"s3://{bucket}/", "")
        
        logger.info(f"Downloading from S3: {bucket}/{key}")
        s3_client.download_file(bucket, key, str(local_path))
        logger.info(f"Downloaded to: {local_path}")
        return True
    
    except Exception as e:
        logger.error(f"Failed to download from S3: {e}")
        return False


async def transcribe_openai(audio_path: Path) -> str:
    """Transcribe audio using OpenAI Whisper API."""
    try:
        from openai import AsyncOpenAI
        
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        
        logger.info(f"Transcribing with OpenAI Whisper: {audio_path}")
        
        with open(audio_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",  # Includes timestamps
            )
        
        return transcript.text
    
    except Exception as e:
        logger.error(f"OpenAI transcription failed: {e}")
        raise


async def transcribe_google(audio_path: Path) -> str:
    """Transcribe audio using Google Speech-to-Text."""
    try:
        from google.cloud import speech_v1
        
        client = speech_v1.SpeechClient()
        
        logger.info(f"Transcribing with Google STT: {audio_path}")
        
        with open(audio_path, "rb") as audio_file:
            content = audio_file.read()
        
        audio = speech_v1.RecognitionAudio(content=content)
        config = speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.MP3,
            sample_rate_hertz=16000,
            language_code="en-US",
            enable_automatic_punctuation=True,
        )
        
        response = client.recognize(config=config, audio=audio)
        
        transcript = " ".join([result.alternatives[0].transcript for result in response.results])
        return transcript
    
    except Exception as e:
        logger.error(f"Google STT failed: {e}")
        raise


async def transcribe_deepgram(audio_path: Path) -> str:
    """Transcribe audio using Deepgram."""
    try:
        from deepgram import DeepgramClient, PrerecordedOptions
        
        client = DeepgramClient(DEEPGRAM_API_KEY)
        
        logger.info(f"Transcribing with Deepgram: {audio_path}")
        
        with open(audio_path, "rb") as audio_file:
            buffer_data = audio_file.read()
        
        options = PrerecordedOptions(
            model="nova-2",
            smart_format=True,
            punctuate=True,
        )
        
        response = client.listen.prerecorded.v("1").transcribe_file(
            {"buffer": buffer_data},
            options,
        )
        
        transcript = response.results.channels[0].alternatives[0].transcript
        return transcript
    
    except Exception as e:
        logger.error(f"Deepgram transcription failed: {e}")
        raise


async def send_transcript_webhook(room_name: str, transcript: str, s3_path: str):
    """Send transcript to webhook endpoint."""
    if not TRANSCRIPT_WEBHOOK_URL:
        logger.info("No webhook URL configured")
        return
    
    try:
        payload = {
            "room_name": room_name,
            "transcript": transcript,
            "audio_file": s3_path,
            "stt_provider": STT_PROVIDER,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TRANSCRIPT_WEBHOOK_URL,
                json=payload,
                timeout=30.0,
            )
            logger.info(f"Webhook sent: {response.status_code}")
    
    except Exception as e:
        logger.error(f"Failed to send webhook: {e}")


async def process_recording(s3_path: str, room_name: str):
    """Main processing function."""
    logger.info(f"Processing recording: {s3_path}")
    
    # Create temp directory
    temp_dir = Path("/tmp/livekit-recordings")
    temp_dir.mkdir(exist_ok=True)
    
    local_path = temp_dir / f"{room_name}.mp3"
    
    try:
        # Download from S3
        if not await download_from_s3(s3_path, local_path):
            logger.error("Failed to download audio file")
            return
        
        # Transcribe based on provider
        if STT_PROVIDER == "openai":
            transcript = await transcribe_openai(local_path)
        elif STT_PROVIDER == "google":
            transcript = await transcribe_google(local_path)
        elif STT_PROVIDER == "deepgram":
            transcript = await transcribe_deepgram(local_path)
        else:
            logger.error(f"Unknown STT provider: {STT_PROVIDER}")
            return
        
        logger.info(f"Transcript generated ({len(transcript)} chars)")
        logger.info(f"Transcript: {transcript[:200]}...")
        
        # Send to webhook
        await send_transcript_webhook(room_name, transcript, s3_path)
        
        logger.info("Processing complete!")
    
    finally:
        # Cleanup
        if local_path.exists():
            local_path.unlink()
            logger.info(f"Cleaned up temp file: {local_path}")


async def handle_egress_webhook(webhook_data: dict):
    """Handle LiveKit egress webhook."""
    event_type = webhook_data.get("event")
    
    if event_type != "egress_ended":
        logger.info(f"Ignoring event: {event_type}")
        return
    
    egress_info = webhook_data.get("egressInfo", {})
    room_name = egress_info.get("roomName")
    status = egress_info.get("status")
    
    if status != "EGRESS_COMPLETE":
        logger.warning(f"Egress not complete: {status}")
        return
    
    # Get file output location
    file_results = egress_info.get("fileResults", [])
    if not file_results:
        logger.error("No file results in webhook")
        return
    
    file_info = file_results[0]
    s3_path = file_info.get("location")  # e.g., s3://bucket/calls/room-name.mp3
    
    if not s3_path:
        logger.error("No S3 path in file results")
        return
    
    logger.info(f"Egress complete for room: {room_name}")
    await process_recording(s3_path, room_name)


if __name__ == "__main__":
    # Example: Process a specific recording
    import sys
    
    if len(sys.argv) > 1:
        room_name = sys.argv[1]
        s3_path = f"s3://{S3_BUCKET}/calls/{room_name}.mp3"
        asyncio.run(process_recording(s3_path, room_name))
    else:
        print("Usage: python process_recording.py <room_name>")
        print("Or deploy as webhook handler for LiveKit egress events")
