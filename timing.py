"""Monotonic job timing with an ETA derived from observed progress."""

from datetime import datetime, timedelta
from time import monotonic


def duration(seconds):
    minutes, sec = divmod(max(0, round(seconds)), 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:d}:{minute:02d}:{sec:02d}" if hours else f"{minute:02d}:{sec:02d}"


class Timeline:
    def __init__(self):
        self.started = self.sample_at = monotonic()
        self.fraction = self.visible = 0.0
        self.sample_fraction = 0.0
        self.rate = None
        self.finalized = False

    def advance(self, fraction):
        fraction = max(0.0, min(0.995, fraction))
        if fraction <= self.fraction:
            return
        now = monotonic()
        seconds = now - self.sample_at
        if seconds >= 0.15:
            instant = (fraction - self.sample_fraction) / seconds
            self.rate = instant if self.rate is None else 0.3 * instant + 0.7 * self.rate
            self.sample_at = now
            self.sample_fraction = fraction
        self.fraction = fraction

    def line(self, state=""):
        elapsed = duration(monotonic() - self.started)
        if state:
            return f"{state}  ·  Elapsed {elapsed}"
        if self.finalized:
            return f"Elapsed {elapsed}  ·  Finalizing…"
        if self.rate is None or self.fraction < 0.02:
            return f"Elapsed {elapsed}  ·  Estimating remaining time…"
        remaining = max(1, (1 - self.fraction) / self.rate)
        finish = (datetime.now() + timedelta(seconds=min(remaining, 604800))).strftime("%H:%M:%S")
        if remaining > 604800:
            return f"Elapsed {elapsed}  ·  Estimated remaining more than 7 days"
        return f"Elapsed {elapsed}  ·  ~{duration(remaining)} left  ·  Est. 100% at {finish}"
