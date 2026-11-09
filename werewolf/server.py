"""Local-only spectator server. Models never receive this server as a tool."""

from __future__ import annotations

import argparse
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

from . import providers
from .credentials import load_local_credentials
from .providers import PlayerConfig
from .runner import Runner


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
NAMES = ["Atlas", "Mei", "Orion", "Lin", "Nova", "Jun", "Echo", "Yue",
         "Rowan", "An", "Sage", "Kai"]
PERSONALITIES = ["Analytical and concise", "Warm but skeptical", "Bold and direct",
                 "Patient and observant", "Playful and persuasive", "Methodical",
                 "Curious and questioning", "Calm and diplomatic", "Competitive",
                 "Cautious and precise", "Reflective", "Confident and expressive"]
PROVIDERS = {"demo", "deepseek", "openai", "openai_subscription"}


def parse_setup(body):
    """Validate local setup without accepting secrets, endpoints, or code."""
    if not isinstance(body, dict):
        raise ValueError("Setup must be a JSON object.")
    if set(body) - {"seed", "language", "players", "preset", "allow_format_repair"}:
        raise ValueError("Unknown setup field.")
    if type(body.get("allow_format_repair", False)) is not bool:
        raise ValueError("allow_format_repair must be a boolean.")
    preset = body.get("preset", "demo")
    if preset not in {"demo", "deepseek_flash"}:
        raise ValueError("Unknown game preset.")
    language = body.get("language", "en")
    if language not in {"en", "zh"}:
        raise ValueError("Language must be en or zh.")
    seed = body.get("seed", 1)
    if type(seed) is not int or not 0 <= seed <= 2**53 - 1:
        raise ValueError("Seed must be an integer from 0 through 9007199254740991.")
    players = body.get("players")
    if players is not None and "preset" in body:
        raise ValueError("Choose either a preset or explicit player configurations.")
    if players is None and preset == "deepseek_flash":
        return [providers.deepseek_flash_config(i + 1, name,
                    personality=PERSONALITIES[i], language=language)
                for i, name in enumerate(NAMES)], seed, language
    if players is None:
        players = [{"seat": i + 1, "name": name, "provider": "demo",
                    "model": "scripted", "personality": PERSONALITIES[i]}
                   for i, name in enumerate(NAMES)]
    if not isinstance(players, list) or len(players) != 12:
        raise ValueError("Exactly twelve player configurations are required.")
    configs = []
    allowed = {"seat", "name", "provider", "model", "personality",
               "temperature", "max_tokens", "language", "thinking", "reasoning_effort"}
    for index, player in enumerate(players, 1):
        if not isinstance(player, dict) or set(player) - allowed:
            raise ValueError("Player configuration has unsupported fields.")
        if type(player.get("seat", index)) is not int or player.get("seat", index) != index:
            raise ValueError("Players must be in seat order, 1 through 12.")
        provider = player.get("provider", "demo")
        if provider not in PROVIDERS:
            raise ValueError("Unknown provider.")
        name = player.get("name", NAMES[index - 1])
        model = player.get("model", "scripted" if provider == "demo" else
                           providers.DEEPSEEK_FLASH_MODEL if provider == "deepseek" else "")
        personality = player.get("personality", PERSONALITIES[index - 1])
        if not isinstance(name, str) or not name.strip() or len(name) > 50:
            raise ValueError("Player names must contain 1–50 characters.")
        if not isinstance(model, str) or not model.strip() or len(model) > 120:
            raise ValueError("Each player needs a model identifier of 1–120 characters.")
        if not isinstance(personality, str) or len(personality) > 2000:
            raise ValueError("Personality must be text of at most 2000 characters.")
        thinking = player.get("thinking")
        reasoning_effort = player.get("reasoning_effort")
        temperature = player.get("temperature", None if provider == "openai_subscription" or
                                 thinking == "enabled" else 0.7)
        max_tokens = player.get("max_tokens", None if provider == "openai_subscription" else
                                providers.DEEPSEEK_FLASH_MAX_TOKENS if provider == "deepseek" else 500)
        if temperature is not None and (isinstance(temperature, bool) or
                not isinstance(temperature, (int, float)) or
                not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise ValueError("Temperature must be null or a number between 0 and 2.")
        if max_tokens is not None and (type(max_tokens) is not int or not 128 <= max_tokens <= 8192):
            raise ValueError("Token budget must be null or an integer between 128 and 8192.")
        configs.append(PlayerConfig(seat=index, name=name.strip(), provider=provider,
                                    model=model.strip(), personality=personality,
                                    temperature=temperature, max_tokens=max_tokens,
                                    language=language, thinking=thinking,
                                    reasoning_effort=reasoning_effort))
    return configs, seed, language


class Controller:
    """A single inference worker with detached, nonblocking spectator snapshots."""

    def __init__(self, initial_setup=None, restored_runner=None, *, allow_format_repair=False):
        if type(allow_format_repair) is not bool:
            raise ValueError("allow_format_repair must be a boolean.")
        self.condition = threading.Condition(threading.RLock())
        self.runner = None
        self.views = {}
        self.history = []
        self.playing = False
        self.busy = False
        self.step_requested = False
        self.stopped = False
        self.failure = None
        if restored_runner is None:
            setup = deepcopy(initial_setup or {})
            setup.setdefault("allow_format_repair", allow_format_repair)
            self.create(setup)
        else:
            self.runner = restored_runner
            self._capture()
        self.worker = threading.Thread(target=self._work, daemon=True, name="werewolf-turns")
        self.worker.start()

    def _capture(self):
        views = {"mystery": self.runner.snapshot("mystery"),
                 "omniscient": self.runner.snapshot("omniscient")}
        for seat in range(1, 13):
            views[f"player:{seat}"] = self.runner.snapshot("player", seat)
        self.views = deepcopy(views)
        max_step = int(views["mystery"].get("max_step", views["mystery"].get("step", 0)))
        while len(self.history) <= max_step:
            at = len(self.history)
            checkpoint = {"mystery": self.runner.replay(at, "mystery"),
                          "omniscient": self.runner.replay(at, "omniscient")}
            for seat in range(1, 13):
                checkpoint[f"player:{seat}"] = self.runner.replay(at, "player", seat)
            self.history.append(deepcopy(checkpoint))

    def create(self, body):
        load_local_credentials()
        configs, seed, language = parse_setup(body)
        with self.condition:
            if self.busy or self.playing or self.step_requested:
                raise RuntimeError("Pause and wait for the current turn before starting a new game.")
            runner = Runner(configs, seed=seed, language=language,
                            allow_format_repair=body.get("allow_format_repair", False))
            self.runner = runner
            self.history = []
            self.failure = None
            self._capture()
            return self.snapshot()

    def snapshot(self, mode="mystery", seat=None, at=None):
        if mode not in {"mystery", "omniscient", "player"}:
            raise ValueError("Unknown spectator perspective.")
        if mode == "player" and (type(seat) is not int or not 1 <= seat <= 12):
            raise ValueError("Follow a player requires a seat from 1 through 12.")
        key = f"player:{seat}" if mode == "player" else mode
        with self.condition:
            if at is None:
                result = deepcopy(self.views[key])
                if self.failure:
                    result.update(status="error", error=self.failure)
                elif result.get("winner"):
                    result["status"] = "finished"
                elif self.busy or self.playing or self.step_requested:
                    result["status"] = "running"
            else:
                if type(at) is not int or not 0 <= at < len(self.history):
                    raise ValueError("Replay checkpoint is out of range.")
                result = deepcopy(self.history[at][key])
                result["status"] = "finished" if result.get("winner") else "paused"
            result["max_step"] = len(self.history) - 1
            result["mode"] = mode
            result["busy"] = self.busy or self.step_requested
            result["playing"] = self.playing
            return result

    def control(self, action):
        with self.condition:
            if action == "pause":
                self.playing = False
                self.step_requested = False
            elif self.views["mystery"].get("winner"):
                raise ValueError("This game is complete. Start a new game to continue.")
            elif action == "play":
                self.failure = None
                self.playing = True
            elif action == "step":
                if self.playing or self.busy or self.step_requested:
                    raise RuntimeError("Pause and wait for the current turn before stepping.")
                self.failure = None
                self.step_requested = True
            else:
                raise ValueError("Unknown control action.")
            self.condition.notify_all()
            return self.snapshot()

    def _work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped or self.playing or self.step_requested)
                if self.stopped:
                    return
                self.busy = True
                self.step_requested = False
                runner = self.runner
            try:
                runner.step()
                with self.condition:
                    self._capture()
                    state = self.views["mystery"]
                    if state.get("winner") or state.get("status") == "error":
                        self.playing = False
            except Exception:
                # Never send exception text, auth headers, or provider payloads to the UI.
                with self.condition:
                    self.failure = "The turn could not complete. Retry the step or check provider setup."
                    self.playing = False
            finally:
                with self.condition:
                    self.busy = False
                    self.condition.notify_all()
            with self.condition:
                if self.playing and not self.stopped:
                    self.condition.wait(timeout=0.35)

    def export(self):
        with self.condition:
            if self.busy:
                raise RuntimeError("Pause and wait for the current turn before exporting.")
            return deepcopy(self.runner.export())

    def close(self):
        with self.condition:
            self.stopped = True
            self.playing = False
            self.condition.notify_all()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, controller=None):
        self.controller = controller or Controller()
        super().__init__(address, Handler)

    def server_close(self):
        self.controller.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server: LocalServer

    def log_message(self, format, *args):
        # Local request logs omit payloads and query strings.
        pass

    def _allowed_host(self):
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed |= {"127.0.0.1", "localhost"}
        return self.headers.get("Host", "") in allowed

    def _send(self, status, payload, content_type="application/json; charset=utf-8", download=False):
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if isinstance(payload, (dict, list)) else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="werewolf-private-archive.json"')
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code, message):
        self._send(code, {"error": message})

    def do_GET(self):
        if not self._allowed_host():
            self._error(HTTPStatus.FORBIDDEN, "Only local spectator access is allowed.")
            return
        route = urlsplit(self.path)
        try:
            if route.path == "/api/state":
                query = parse_qs(route.query)
                seat = int(query["seat"][0]) if "seat" in query else None
                at = int(query["at"][0]) if "at" in query else None
                self._send(200, self.server.controller.snapshot(query.get("mode", ["mystery"])[0], seat, at))
            elif route.path == "/api/providers":
                load_local_credentials()
                self._send(200, {"deepseek": {
                    "configured": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
                    "model": providers.DEEPSEEK_FLASH_MODEL,
                }})
            elif route.path == "/api/export":
                self._send(200, self.server.controller.export(), download=True)
            else:
                assets = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/index.html": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/style.css": ("style.css", "text/css; charset=utf-8")}
                if route.path not in assets:
                    self._error(404, "Not found.")
                    return
                filename, mime = assets[route.path]
                self._send(200, (WEB_ROOT / filename).read_bytes(), mime)
        except ValueError as exc:
            self._error(400, str(exc))
        except RuntimeError as exc:
            self._error(409, str(exc))
        except Exception:
            self._error(500, "The local server could not complete this request.")

    def do_POST(self):
        if not self._allowed_host():
            self._error(403, "Only local spectator access is allowed.")
            return
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if ((origin is not None and origin != f"http://{host}") or
                self.headers.get("Sec-Fetch-Site", "none") not in {"same-origin", "none"}):
            self._error(403, "State changes require same-origin access.")
            return
        if self.headers.get_content_type() != "application/json":
            self._error(415, "Use application/json.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 131072:
                raise ValueError("Request exceeds the allowed size.")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Request must be a JSON object.")
            path = urlsplit(self.path).path
            if path == "/api/game":
                result = self.server.controller.create(body)
            elif path == "/api/providers/deepseek/check":
                if set(body) - {"language"} or body.get("language", "en") not in {"en", "zh"}:
                    raise ValueError("Connection check accepts only language en or zh.")
                load_local_credentials()
                result = providers.check_deepseek(body.get("language", "en"))
            elif path in {"/api/step", "/api/play", "/api/pause"}:
                if body:
                    raise ValueError("Game controls accept no settings; configure a new game to change its policy.")
                result = self.server.controller.control(path.rsplit("/", 1)[1])
            else:
                self._error(404, "Not found.")
                return
            self._send(200, result)
        except (ValueError, UnicodeDecodeError, providers.ProviderError) as exc:
            self._error(400, str(exc))
        except RuntimeError as exc:
            self._error(409, str(exc))
        except Exception:
            self._error(500, "The local server could not complete this request.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the local Werewolf spectator application.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--language", choices=("en", "zh"), default="en")
    parser.add_argument("--preset", choices=("demo", "deepseek_flash"), default="demo")
    parser.add_argument("--check-deepseek", action="store_true",
                        help="Verify one real Flash speech request without creating a game.")
    parser.add_argument("--resume", type=Path,
                        help="Restore a trusted local private archive, paused, without inference.")
    parser.add_argument("--allow-format-repair", action="store_true",
                        help="Opt a new game into one automatic format-correction attempt per decision (default: off).")
    args = parser.parse_args(argv)
    try:
        load_local_credentials()
        if args.resume and (args.check_deepseek or args.preset != "demo" or args.allow_format_repair):
            parser.error("--resume preserves the archived policy and cannot be combined with --check-deepseek, --preset, or --allow-format-repair.")
        if args.check_deepseek:
            result = providers.check_deepseek(args.language)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return
        if args.resume:
            controller = Controller(restored_runner=Runner.from_archive(
                json.loads(args.resume.read_text(encoding="utf-8"))))
        else:
            controller = Controller({"preset": args.preset, "language": args.language,
                                     "allow_format_repair": args.allow_format_repair})
    except (ValueError, providers.ProviderError) as exc:
        parser.exit(1, f"{exc}\n")
    server = LocalServer(("127.0.0.1", args.port), controller)
    print(f"Werewolf spectator: http://127.0.0.1:{server.server_address[1]}", flush=True)
    print("Saved game restored and paused; press Play to resume inference." if args.resume else
          "DeepSeek Flash players configured; press Play to start inference." if args.preset == "deepseek_flash"
          else "Default players are scripted demo players. Configure live providers before evaluating AI.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
