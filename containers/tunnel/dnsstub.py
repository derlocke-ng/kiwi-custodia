#!/usr/bin/env python3
"""A resolver for a box on a remote-DNS exit.

A kiwi-proxy exit in remote DNS mode (what Tor needs) runs no resolver in its
gateway: a browser hands names to the SOCKS5 forwarder and nothing ever asks for
an A record. An ordinary program in a box does ask, through libc, over UDP — and
UDP has nowhere to go. This answers on 127.0.0.3:53, UDP and TCP, and carries
each query over TCP through the forwarder to a public resolver, so the name is
resolved beyond the exit, which is what "remote" means. Nothing is cached and
nothing is interpreted: bytes in, bytes out.

Standard library only; it runs in the tunnel image beside tun2socks.
"""

from __future__ import annotations

import argparse
import contextlib
import socket
import struct
import sys
import threading

TIMEOUT = 8.0


def socks5_connect(socks: tuple[str, int], dest: tuple[str, int]) -> socket.socket:
    """A TCP connection to `dest`, through the no-auth SOCKS5 at `socks`."""
    s = socket.create_connection(socks, timeout=TIMEOUT)
    try:
        s.sendall(b"\x05\x01\x00")
        if _recv(s, 2) != b"\x05\x00":
            raise OSError("socks5: no-auth refused")
        host, port = dest
        try:
            addr = b"\x01" + socket.inet_aton(host)
        except OSError:
            raw = host.encode("idna")
            addr = b"\x03" + bytes([len(raw)]) + raw
        s.sendall(b"\x05\x01\x00" + addr + struct.pack("!H", port))
        head = _recv(s, 4)
        if head[1] != 0:
            raise OSError(f"socks5: connect refused ({head[1]})")
        if head[3] == 1:
            _recv(s, 4 + 2)
        elif head[3] == 3:
            _recv(s, _recv(s, 1)[0] + 2)
        elif head[3] == 4:
            _recv(s, 16 + 2)
        return s
    except Exception:
        s.close()
        raise


def _recv(s: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise OSError("connection closed")
        buf += chunk
    return buf


def resolve(query: bytes, socks: tuple[str, int], upstream: tuple[str, int]) -> bytes:
    """One DNS message over TCP (RFC 7766 framing) through the exit."""
    s = socks5_connect(socks, upstream)
    try:
        s.sendall(struct.pack("!H", len(query)) + query)
        (length,) = struct.unpack("!H", _recv(s, 2))
        return _recv(s, length)
    finally:
        s.close()


def servfail(query: bytes) -> bytes:
    """The query echoed back as SERVFAIL, so a client fails fast rather than
    waiting for a timeout when the exit cannot be reached."""
    if len(query) < 12:
        return b""
    ident, flags = struct.unpack("!HH", query[:4])
    flags = 0x8000 | (flags & 0x0100) | 0x0002  # QR, keep RD, RCODE=2
    return struct.pack("!HH", ident, flags) + query[4:6] + b"\x00\x00\x00\x00\x00\x00" + query[12:]


def serve_udp(
    listen: str, socks: tuple[str, int], upstream: tuple[str, int], port: int = 53
) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((listen, port))

    def answer(query: bytes, client: tuple) -> None:
        try:
            reply = resolve(query, socks, upstream)
        except Exception as exc:  # noqa: BLE001 - one bad query must not take the stub down
            print(f"dnsstub: udp query failed: {exc}", file=sys.stderr, flush=True)
            reply = servfail(query)
        if reply:
            if len(reply) > 512 and not _edns(query):
                # A client without EDNS takes 512 bytes: truncate and say so (TC),
                # and it asks again over TCP.
                reply = reply[:2] + bytes([reply[2] | 0x02]) + reply[3:512]
            with contextlib.suppress(OSError):
                sock.sendto(reply, client)

    while True:
        query, client = sock.recvfrom(4096)
        threading.Thread(target=answer, args=(query, client), daemon=True).start()


def _edns(query: bytes) -> bool:
    """Whether the client said it takes more than 512 bytes (an OPT record)."""
    return len(query) >= 12 and struct.unpack("!H", query[10:12])[0] > 0


def serve_tcp(
    listen: str, socks: tuple[str, int], upstream: tuple[str, int], port: int = 53
) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((listen, port))
    srv.listen(64)

    def answer(conn: socket.socket) -> None:
        with conn:
            conn.settimeout(TIMEOUT)
            try:
                (length,) = struct.unpack("!H", _recv(conn, 2))
                query = _recv(conn, length)
                try:
                    reply = resolve(query, socks, upstream)
                except Exception as exc:  # noqa: BLE001
                    print(f"dnsstub: tcp query failed: {exc}", file=sys.stderr, flush=True)
                    reply = servfail(query)
                if reply:
                    conn.sendall(struct.pack("!H", len(reply)) + reply)
            except OSError:
                pass

    while True:
        conn, _ = srv.accept()
        threading.Thread(target=answer, args=(conn,), daemon=True).start()


def hostport(text: str, default_port: int) -> tuple[str, int]:
    host, sep, port = text.rpartition(":")
    if not sep:
        return text, default_port
    return host, int(port)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--listen", default="127.0.0.3")
    ap.add_argument("--socks", default="127.0.0.1:1080")
    ap.add_argument("--upstream", default="1.1.1.1:53")
    ap.add_argument("--port", type=int, default=53)
    a = ap.parse_args(argv)
    socks = hostport(a.socks, 1080)
    upstream = hostport(a.upstream, 53)
    threading.Thread(
        target=serve_tcp, args=(a.listen, socks, upstream, a.port), daemon=True
    ).start()
    serve_udp(a.listen, socks, upstream, a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
