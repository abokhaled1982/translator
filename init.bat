#
# Copyright (c) 2024-2026, Daily
# Modified for Arabic Text-Only Support
#

import os
import sys
import asyncio

from dotenv import load_dotenv
from loguru import logger

# --- ARABISCH FORMATIERUNG IMPORTS ---
import arabic_reshaper
from bidi.algorithm import get_display
from colorama import Fore, Style, init

# Pipecat Imports
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame, TextFrame, TranscriptionFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.groq.stt import GroqSTTService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

load_dotenv(override=True)

# Windows Console Fix
init()
if sys.platform == "win32":
    os.system("chcp 65001 >nul")

# -------------------------------------------------------------------------
# HELPER: Arabisch formatieren
# -------------------------------------------------------------------------
def fix_arabic_text(text):
    try:
        reshaped_text = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except Exception:
        return text

# -------------------------------------------------------------------------
# LOGGER: Zeigt Text sauber im Terminal an
# -------------------------------------------------------------------------
class ArabicTerminalLogger(FrameProcessor):
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            txt = fix_arabic_text(frame.text)
            print(f"\n{Fore.GREEN}🎤 USER: {Style.RESET_ALL} {txt}")
            
        elif isinstance(frame, TextFrame):
            txt = fix_arabic_text(frame.text)
            print(f"{Fore.CYAN}🤖 BOT:  {Style.RESET_ALL} {txt}")

        await self.push_frame(frame, direction)


async def fetch_weather_from_api(params: FunctionCallParams):
    # Einfaches Beispiel
    await params.result_callback({"conditions": "sonnig", "temperature": "30 Grad"})


# Transport Params (Standard belassen, aber Output ist stumm da kein TTS)
transport_params = {
    "daily": lambda: DailyParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
    ),
    "twilio": lambda: FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
    ),
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
    ),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info(f"Starting Arabic Text-Only Bot")

    # 1. STT (Groq) - Arabisch
    stt = GroqSTTService(
        api_key=os.getenv("GROQ_API_KEY"),
        model="whisper-large-v3",
        language="ar" # Zwingt Arabisch
    )

    # 2. LLM (Groq)
    llm = GroqLLMService(api_key=os.getenv("GROQ_API_KEY"))
    llm.register_function("get_current_weather", fetch_weather_from_api)

    # 3. Logger (Formatierer)
    arabic_logger = ArabicTerminalLogger()

    # Tools Definition
    weather_function = FunctionSchema(
        name="get_current_weather",
        description="Get the current weather",
        properties={
            "location": {"type": "string"},
        },
        required=["location"],
    )
    tools = ToolsSchema(standard_tools=[weather_function])

    # 4. System Prompt (Arabisch Anweisung)
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. You speak fluent Arabic. Please respond exclusively in Arabic. Keep it short.",
        },
    ]

    context = LLMContext(messages, tools)
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]
            ),
        ),
    )

    # 5. Pipeline (OHNE TTS)
    pipeline = Pipeline(
        [
            transport.input(),              # Audio Input
            stt,                            # Audio -> Text
            context_aggregator.user(),      # User Context
            llm,                            # Text Generierung
            arabic_logger,                  # <--- ZEIGT ARABISCH IM TERMINAL
            # tts,                          # ENTFERNT
            # transport.output(),           # ENTFERNT (da kein Audio Output nötig)
            context_aggregator.assistant(), # Assistant Context
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client connected")
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()