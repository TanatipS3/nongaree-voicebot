import logging

logger = logging.getLogger("nongaree-agent")


class LatencyTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.stt_done: float = 0
        self.router_start: float = 0
        self.router_done: float = 0
        self.retrieve_start: float = 0
        self.retrieve_done: float = 0
        self.generate_start: float = 0
        self.generate_first_token: float = 0
        self.generate_done: float = 0
        self.tts_chunks: list[dict] = []
        self.first_audio: float = 0
        self.emotions: list[str] = []

    def log_summary(self):
        stt_to_first_audio = (self.first_audio - self.stt_done) * 1000
        router_ms = (self.router_done - self.router_start) * 1000
        retrieve_ms = (self.retrieve_done - self.retrieve_start) * 1000
        generate_ttft = (self.generate_first_token - self.generate_start) * 1000
        generate_total = (self.generate_done - self.generate_start) * 1000
        tts_avg = sum(c["ms"] for c in self.tts_chunks) / max(len(self.tts_chunks), 1)
        emotion_str = " → ".join(self.emotions) if self.emotions else "idle"

        logger.info(
            "\n┌─────────────────────────────────────────┐\n"
            "│  LATENCY BREAKDOWN                      │\n"
            "├──────────────────────┬──────────────────┤\n"
            "│ STT → First Audio    │ %6.0fms          │\n"
            "│ Router node          │ %6.0fms          │\n"
            "│ Retrieve node        │ %6.0fms          │\n"
            "│ LLM TTFT             │ %6.0fms          │\n"
            "│ LLM Total            │ %6.0fms          │\n"
            "│ TTS avg per chunk    │ %6.0fms          │\n"
            "│ TTS chunks count     │ %6d            │\n"
            "│ Emotions             │ %-16s │\n"
            "└──────────────────────┴──────────────────┘",
            stt_to_first_audio,
            router_ms,
            retrieve_ms,
            generate_ttft,
            generate_total,
            tts_avg,
            len(self.tts_chunks),
            emotion_str,
        )


tracker = LatencyTracker()
