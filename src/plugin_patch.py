"""
plugin_patch.py — Monkey-Patch fuer livekit-plugins-google.

Behebt den 1008-Fehler bei Function Calling mit gemini-2.5-flash-native-audio-latest.

Problem:
  In livekit/plugins/google/utils.py wird res.id = msg.call_id gesetzt.
  Wenn call_id None ist, schickt das Plugin eine FunctionResponse mit id=None
  an Google — der Server wirft dann 1008 (policy violation).

Loesung:
  Wir patchen get_tool_results_for_realtime() zur Laufzeit (Monkey-Patch).
  Kein direktes Editieren von .venv-Dateien mehr noetig.
  Patch bleibt stabil ueber pip-Updates hinweg solange der Import-Pfad gleich bleibt.

Verwendung:
  import plugin_patch  # einmal am Anfang von main.py importieren
"""
import logging
from typing import Optional

logger = logging.getLogger("intraunit.plugin_patch")


def _apply() -> None:
    try:
        import livekit.plugins.google.utils as google_utils
        from google.genai import types
        from livekit.agents import llm
        from livekit.agents.types import NOT_GIVEN, NotGivenOr
        from livekit.agents.utils import is_given

        def _patched_get_tool_results_for_realtime(
            chat_ctx: llm.ChatContext,
            *,
            vertexai: bool = False,
            tool_response_scheduling: NotGivenOr[types.FunctionResponseScheduling] = NOT_GIVEN,
        ) -> Optional[types.LiveClientToolResponse]:
            """
            Gepatchte Version von get_tool_results_for_realtime.
            Fix: res.id wird nur gesetzt wenn call_id tatsaechlich vorhanden ist.
            Verhindert 1008 bei gemini-2.5-flash-native-audio-latest.
            """
            function_responses = []
            for msg in chat_ctx.items:
                if msg.type == "function_call_output":
                    res = types.FunctionResponse(
                        name=msg.name,
                        response={"output": msg.output},
                    )
                    if is_given(tool_response_scheduling):
                        res.scheduling = tool_response_scheduling
                    if not vertexai:
                        # PATCH: nur setzen wenn call_id vorhanden (Original setzt immer)
                        if msg.call_id:
                            res.id = msg.call_id
                    function_responses.append(res)

            return (
                types.LiveClientToolResponse(function_responses=function_responses)
                if function_responses
                else None
            )

        # Patch anwenden
        google_utils.get_tool_results_for_realtime = _patched_get_tool_results_for_realtime

        # Auch im realtime_api Modul patchen (das importiert die Funktion direkt)
        try:
            import livekit.plugins.google.realtime.realtime_api as realtime_api
            realtime_api.get_tool_results_for_realtime = _patched_get_tool_results_for_realtime
            logger.info("Plugin-Patch angewendet (utils + realtime_api)")
        except Exception:
            logger.info("Plugin-Patch angewendet (nur utils)")

    except Exception as e:
        logger.error(f"Plugin-Patch fehlgeschlagen: {e} — 1008-Bug moeglicherweise aktiv")


# Patch beim Import automatisch anwenden
_apply()
