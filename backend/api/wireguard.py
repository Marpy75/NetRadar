"""FastAPI router for WireGuard wizard endpoints."""

from fastapi import APIRouter, HTTPException
from backend.services.wireguard import (
    WireGuardAddPeerRequest,
    WireGuardAddPeerResponse,
    WireGuardFinalizeRequest,
    WireGuardFinalizeResponse,
    WireGuardInitRequest,
    WireGuardInitResponse,
    WireGuardService,
)

router = APIRouter(prefix="/api/wireguard", tags=["wireguard"])


@router.post(
    "/init-interface",
    response_model=WireGuardInitResponse,
    summary="Step 1: generate client keys and RouterOS setup commands for a new WireGuard interface",
)
async def init_interface(req: WireGuardInitRequest) -> WireGuardInitResponse:
    """Generates an X25519 client key pair and returns a full set of RouterOS 7.25 commands.

    Commands must be executed manually in the router terminal.
    After running them, call /finalize-interface with the router's public key.
    """
    try:
        return WireGuardService.init_new_interface(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/finalize-interface",
    response_model=WireGuardFinalizeResponse,
    summary="Step 2: generate client .conf and QR after the router's public key is known",
)
async def finalize_interface(req: WireGuardFinalizeRequest) -> WireGuardFinalizeResponse:
    """Combines the client private key (from Step 1) with the router's public key to produce
    a ready-to-use WireGuard client config and SVG QR code.

    The private key is NOT stored on the backend between requests.
    """
    if not req.client_private_key or not req.server_public_key:
        raise HTTPException(
            status_code=422,
            detail="Both client_private_key and server_public_key are required.",
        )
    try:
        return WireGuardService.finalize_new_interface(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/add-peer",
    response_model=WireGuardAddPeerResponse,
    summary="Single-step: add a new peer to an existing WireGuard interface",
)
async def add_peer(req: WireGuardAddPeerRequest) -> WireGuardAddPeerResponse:
    """Generates an X25519 client key pair, the RouterOS peer-add command,
    a client .conf file, and an SVG QR code in a single request.

    The client private key is returned once and not persisted.
    """
    if not req.server_public_key:
        raise HTTPException(
            status_code=422,
            detail="server_public_key is required.",
        )
    try:
        return WireGuardService.add_peer_to_existing(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
