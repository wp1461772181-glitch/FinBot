#!/usr/bin/env python3
"""Local TCP forwarder: 127.0.0.1:<port> -> HTTP CONNECT proxy -> <target>.

The Muse VM blocks raw outbound TCP; only a CONNECT tunnel through the egress
proxy (HTTPS_PROXY) reaches Supabase. Point DATABASE_URL at this listener.
Credentials come only from the environment and are never logged.

env: HTTPS_PROXY (required), DB_TUNNEL_TARGET (default
db.doftncswxfxbakyjlnfv.supabase.co:5432), DB_TUNNEL_PORT (default 15432).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import signal
import sys
import urllib.parse

log = logging.getLogger("db_tunnel")
TARGET = os.getenv("DB_TUNNEL_TARGET", "db.doftncswxfxbakyjlnfv.supabase.co:5432")
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.getenv("DB_TUNNEL_PORT", "15432"))


def proxy_settings() -> tuple[str, int, str]:
    raw = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not raw:
        raise SystemExit("HTTPS_PROXY is not set")
    parsed = urllib.parse.urlparse(raw)
    auth = ""
    if parsed.username:
        user = urllib.parse.unquote(parsed.username)
        password = urllib.parse.unquote(parsed.password or "")
        auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    return parsed.hostname, parsed.port or 3128, auth


async def open_tunnel(host: str, port: int, auth: str, target: str):
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 15)
    request = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
    if auth:
        request += f"Proxy-Authorization: Basic {auth}\r\n"
    writer.write((request + "\r\n").encode())
    await writer.drain()
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
    status = head.split(b"\r\n", 1)[0].decode(errors="replace")
    if " 200" not in status:
        writer.close()
        raise ConnectionError(f"CONNECT refused: {status.split(' ', 1)[-1][:60]}")
    return reader, writer


async def pump(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError, OSError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_r, client_w):
    host, port, auth = proxy_settings()
    try:
        up_r, up_w = await open_tunnel(host, port, auth, TARGET)
    except Exception as exc:  # noqa: BLE001
        log.warning("tunnel open failed: %s", type(exc).__name__ + ": " + str(exc)[:80])
        client_w.close()
        return
    await asyncio.gather(pump(client_r, up_w), pump(up_r, client_w))


async def main() -> None:
    proxy_settings()  # fail fast if misconfigured
    server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
    log.info("listening on %s:%s -> %s via proxy", LISTEN_HOST, LISTEN_PORT, TARGET)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    async with server:
        await stop.wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", stream=sys.stderr)
    asyncio.run(main())
