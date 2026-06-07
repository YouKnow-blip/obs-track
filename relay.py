"""Публичный релей (ретранслятор) для OBS Remote Control.

Разворачивается на Railway (или любом хостинге с публичным HTTPS).
Связывает сервер стримера и клиента оператора по «коду комнаты»,
чтобы не нужно было пробрасывать порты на роутере.

Адреса:
    /<комната>/host    — подключается сервер стримера
    /<комната>/client  — подключается клиент оператора

Релей не знает токена и не расшифровывает команды — он лишь пересылает
сообщения между двумя сторонами комнаты. Проверка токена всегда
остаётся на сервере стримера.
"""
import asyncio
import http
import json
import os

import websockets

# room -> {"host": ws | None, "client": ws | None}
ROOMS: dict[str, dict] = {}


def _room(name: str) -> dict:
    if name not in ROOMS:
        ROOMS[name] = {"host": None, "client": None}
    return ROOMS[name]


async def _safe_send(ws, message: str) -> None:
    if ws is None:
        return
    try:
        await ws.send(message)
    except Exception:  # noqa: BLE001
        pass


def _parse_path(path: str):
    """/<room>/<role> -> (room, role) или (None, None)."""
    parts = [p for p in path.split("?")[0].split("/") if p]
    if len(parts) != 2:
        return None, None
    room, role = parts[0], parts[1]
    if role not in ("host", "client"):
        return None, None
    return room, role


async def handler(ws) -> None:
    path = getattr(ws, "path", "/")
    room_name, role = _parse_path(path)
    if room_name is None:
        await _safe_send(ws, json.dumps({"sys": "error", "reason": "bad_path"}))
        await ws.close()
        return

    room = _room(room_name)
    # Заменяем старое подключение той же роли, если оно было
    old = room.get(role)
    if old is not None:
        try:
            await old.close()
        except Exception:  # noqa: BLE001
            pass
    room[role] = ws

    other_role = "client" if role == "host" else "host"
    # Уведомляем обе стороны о присутствии друг друга
    if role == "client":
        await _safe_send(room.get("host"), json.dumps({"sys": "client_online"}))
        await _safe_send(ws, json.dumps({"sys": "host_online" if room.get("host") else "host_offline"}))
    else:  # host
        await _safe_send(room.get("client"), json.dumps({"sys": "host_online"}))
        if room.get("client"):
            await _safe_send(ws, json.dumps({"sys": "client_online"}))

    print(f"[relay] {role} подключён к комнате '{room_name}'", flush=True)

    try:
        async for raw in ws:
            target = room.get(other_role)
            await _safe_send(target, raw)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if room.get(role) is ws:
            room[role] = None
        # Уведомляем партнёра об отключении
        if role == "client":
            await _safe_send(room.get("host"), json.dumps({"sys": "client_offline"}))
        else:
            await _safe_send(room.get("client"), json.dumps({"sys": "host_offline"}))
        if not room.get("host") and not room.get("client"):
            ROOMS.pop(room_name, None)
        print(f"[relay] {role} отключён от комнаты '{room_name}'", flush=True)


async def process_request(path, request_headers):
    """Отвечаем HTTP 200 на обычные запросы (healthcheck Railway).

    Если это WebSocket-рукопожатие (есть заголовок Upgrade) — возвращаем None,
    чтобы продолжить апгрейд до WebSocket.
    """
    try:
        upgrade = request_headers.get("Upgrade", "") or request_headers.get("upgrade", "")
    except Exception:  # noqa: BLE001
        upgrade = ""
    if str(upgrade).lower() != "websocket":
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"OBS relay running\n"
    return None


async def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    print(f"[relay] запуск на 0.0.0.0:{port}", flush=True)
    async with websockets.serve(
        handler,
        "0.0.0.0",
        port,
        process_request=process_request,
        ping_interval=20,
        ping_timeout=20,
        max_size=16 * 1024 * 1024,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
