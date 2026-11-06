"""NetRadar FastAPI application entry point.

Usage:
    python -m backend.main              # Simulator mode (default)
    python -m backend.main --real       # RouterOS REST API mode (requires NETRADAR_CONFIG)
    python -m backend.main --port 8080  # Custom port
"""

import argparse
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from backend.adapters.base import BaseNetworkAdapter
from backend.adapters.simulator import SimulatorAdapter
from backend.api import wireguard_router
from backend.services.aggregator import TrafficAggregator
from backend.services.classifier import DeviceClassifier

logger = logging.getLogger("netradar")

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts state frames."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.info("WS client connected. Total: %d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.info("WS client disconnected. Total: %d", len(self._connections))

    @property
    def client_count(self) -> int:
        return len(self._connections)

    async def broadcast(self, payload: str) -> None:
        dead: set[WebSocket] = set()
        for ws in self._connections.copy():
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._connections -= dead


# ---------------------------------------------------------------------------
# Global state (set during app lifespan)
# ---------------------------------------------------------------------------

manager = ConnectionManager()
_aggregator: TrafficAggregator | None = None


def get_aggregator() -> TrafficAggregator:
    assert _aggregator is not None, "Aggregator not initialized"
    return _aggregator


# ---------------------------------------------------------------------------
# Background polling loop
# ---------------------------------------------------------------------------

async def polling_loop() -> None:
    """Polls the adapter and broadcasts NetworkStateFrame to all WebSocket clients."""
    agg = get_aggregator()
    logger.info("Polling loop started.")
    while True:
        try:
            frame = await agg.build_frame()
            if manager.client_count > 0:
                await manager.broadcast(frame.model_dump_json())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Polling error: %s", exc)

        # Respect adaptive interval if adapter supports it
        interval: float = 2.0
        if hasattr(agg.adapter, "adaptive_controller"):
            interval = agg.adapter.adaptive_controller.current_interval
        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(adapter: BaseNetworkAdapter) -> FastAPI:
    """Creates and configures the FastAPI application with the given adapter."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        global _aggregator
        _aggregator = TrafficAggregator(
            adapter=adapter,
            classifier=DeviceClassifier(),
        )
        task = asyncio.create_task(polling_loop())
        logger.info("NetRadar started.")
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await adapter.close()
            logger.info("NetRadar stopped.")

    app = FastAPI(
        title="NetRadar",
        description="Local network monitoring dashboard for MikroTik RouterOS 7.25",
        version="1.0.0",
        lifespan=lifespan,
        # Docs disabled: app is self-contained and tested via pytest
        docs_url=None,
        redoc_url=None,
    )

    # WireGuard wizard REST endpoints
    app.include_router(wireguard_router)

    # WebSocket state stream
    @app.websocket("/ws/network")
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await manager.connect(ws)
        # Send initial state immediately upon connection
        try:
            agg = get_aggregator()
            initial_frame = await agg.build_frame()
            await ws.send_text(initial_frame.model_dump_json())
        except Exception as exc:
            logger.debug("Could not send immediate initial frame: %s", exc)
        try:
            while True:
                # Keep connection alive; client may send pings
                data = await ws.receive_text()
                # Ignore client messages; server is push-only
                _ = data
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception:
            manager.disconnect(ws)

    # Serve static files; html=True serves index.html at /
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(static_dir), html=True),
            name="static",
        )

    return app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NetRadar - local network monitoring dashboard"
    )
    p.add_argument(
        "--real",
        action="store_true",
        help="Use real RouterOS REST adapter (requires NETRADAR_CONFIG env var). "
             "Without this flag the simulator runs by default.",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--log-level", default="info")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.real:
        try:
            from backend.adapters.routeros import RouterOSConfig, RouterOSRestAdapter
            config = RouterOSConfig.from_env()
            adapter: BaseNetworkAdapter = RouterOSRestAdapter(config)
            logger.info("RouterOS adapter: %s:%d", config.host, config.port)
        except Exception as exc:
            logger.error("RouterOS adapter init failed: %s", exc)
            sys.exit(1)
    else:
        adapter = SimulatorAdapter()
        logger.info("Simulator adapter active. Subnet: 10.20.0.0/24")

    app = create_app(adapter)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
