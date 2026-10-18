"""Device hub for remote control. Every client is a device that publishes its playback state; any device can
send commands to another one (phone controls the PC and vice versa)."""
import asyncio
import json
import logging

log = logging.getLogger("remote")


class Hub:
    def __init__(self):
        self.devices: dict[str, dict] = {}
        self._loop = None

    def snapshot(self):
        return [{"id": d["id"], "name": d["name"], "kind": d["kind"], "state": d["state"]} for d in self.devices.values()]

    async def _send(self, dev, msg):
        try:
            await dev["ws"].send_text(json.dumps(msg, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass

    async def broadcast(self, msg, exclude=None):
        await asyncio.gather(*(self._send(d, msg) for d in list(self.devices.values()) if d["id"] != exclude))

    def broadcast_threadsafe(self, msg):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(msg), self._loop)

    async def handle(self, ws, device_id, name, kind):
        self._loop = asyncio.get_running_loop()
        await ws.accept()
        old = self.devices.get(device_id)
        dev = {"id": device_id, "name": name, "kind": kind, "state": dict(old["state"]) if old else {}, "ws": ws}
        self.devices[device_id] = dev
        if old:
            try:
                await old["ws"].close()
            except Exception:  # noqa: BLE001
                pass
        await self._send(dev, {"type": "devices", "devices": self.snapshot(), "you": device_id})
        await self.broadcast({"type": "devices", "devices": self.snapshot()}, exclude=device_id)
        try:
            while True:
                try:
                    m = json.loads(await ws.receive_text())
                except ValueError:
                    continue
                t = m.get("type")
                if t == "state":
                    st = m.get("state") or {}
                    dev["state"].update(st)
                    await self.broadcast({"type": "state", "device_id": device_id, "state": st}, exclude=device_id)
                elif t == "command":
                    target = self.devices.get(m.get("target"))
                    if not target or target["id"] == device_id:
                        await self._send(dev, {"type": "error", "error": "A cél eszköz nem érhető el"})
                    else:
                        await self._send(target, {"type": "command", "from": device_id, "from_name": dev["name"],
                                                  "cmd": m.get("cmd"), "args": m.get("args") or {}})
                elif t == "rename":
                    dev["name"] = str(m.get("name") or dev["name"])[:80]
                    await self.broadcast({"type": "devices", "devices": self.snapshot()})
        except Exception:  # noqa: BLE001  (disconnect)
            pass
        finally:
            if self.devices.get(device_id) is dev:
                self.devices.pop(device_id, None)
                await self.broadcast({"type": "devices", "devices": self.snapshot()})
