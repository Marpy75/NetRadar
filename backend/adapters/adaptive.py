"""Adaptive polling controller for high connection count on RouterOS."""


class AdaptivePollingController:
    """Manages dynamic polling intervals based on active connection load.

    Standard interval is 2.0s. If active firewall connections exceed 5000,
    the interval increases to 5.0s to prevent router CPU exhaustion.
    Hysteresis is applied: the interval returns to 2.0s only when the connection
    count falls below 4000.
    """

    def __init__(
        self,
        base_interval_sec: float = 2.0,
        high_load_interval_sec: float = 5.0,
        high_threshold: int = 5000,
        recovery_threshold: int = 4000,
    ) -> None:
        self.base_interval_sec = base_interval_sec
        self.high_load_interval_sec = high_load_interval_sec
        self.high_threshold = high_threshold
        self.recovery_threshold = recovery_threshold
        self._current_interval: float = base_interval_sec
        self._is_high_load: bool = False

    @property
    def current_interval(self) -> float:
        return self._current_interval

    @property
    def is_high_load(self) -> bool:
        return self._is_high_load

    def update(self, connection_count: int) -> float:
        """Updates internal load state and returns the adapted interval in seconds."""
        if not self._is_high_load:
            if connection_count >= self.high_threshold:
                self._is_high_load = True
                self._current_interval = self.high_load_interval_sec
        else:
            if connection_count < self.recovery_threshold:
                self._is_high_load = False
                self._current_interval = self.base_interval_sec

        return self._current_interval
