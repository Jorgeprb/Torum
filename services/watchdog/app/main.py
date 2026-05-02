from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import threading
import time
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import httpx
import psutil
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


ComponentStatus = Literal["OK", "WARN", "FAIL", "RESTARTING", "UNKNOWN"]
RestartTarget = Literal["mt5", "api", "frontend", "bridge", "all", "pc"]


class WatchdogSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    watchdog_admin_token: str
    watchdog_host: str = "127.0.0.1"
    watchdog_port: int = 9200
    torum_root: str = str(Path(__file__).resolve().parents[3])
    mt5_path: str | None = None
    mt5_process_name: str = "terminal64.exe"
    docker_compose_file: str = "docker-compose.yml"
    api_health_url: str = "http://127.0.0.1:8000/api/health"
    frontend_health_url: str = "http://127.0.0.1:5173"
    bridge_health_url: str = "http://127.0.0.1:9100/health"
    api_mt5_status_url: str = "http://127.0.0.1:8000/api/mt5/status"
    max_tick_age_seconds: int = 30
    startup_delay_seconds: int = 6
    bridge_python: str = "python"
    bridge_start_cmd: str | None = None
    frontend_start_cmd: str | None = None


settings = WatchdogSettings()
APP_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = APP_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("torum.watchdog")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_DIR / "watchdog.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
logger.addHandler(handler)
logger.addHandler(logging.StreamHandler())

restart_lock = threading.Lock()
actions: dict[str, dict[str, Any]] = {}


class StatusItem(BaseModel):
    key: str
    label: str
    status: ComponentStatus
    message: str
    updated_at: datetime
    details: dict[str, Any] = {}


class SystemStatus(BaseModel):
    status: ComponentStatus
    message: str
    items: list[StatusItem]
    account_mode: str = "UNKNOWN"
    last_tick_at: datetime | None = None
    last_tick_age_seconds: int | None = None
    action_running: bool = False
    actions: list[dict[str, Any]] = []


class RestartRequest(BaseModel):
    confirmation: str


def require_token(
    authorization: str | None = Header(default=None),
    x_watchdog_token: str | None = Header(default=None),
) -> None:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        token = x_watchdog_token
    if not token or token != settings.watchdog_admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid watchdog token")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _item(key: str, label: str, item_status: ComponentStatus, message: str, details: dict[str, Any] | None = None) -> StatusItem:
    return StatusItem(key=key, label=label, status=item_status, message=message, updated_at=utcnow(), details=details or {})


def _http_json(url: str, timeout: float = 2.5) -> tuple[bool, dict[str, Any] | None, str | None]:
    try:
        response = httpx.get(url, timeout=timeout)
        if response.status_code >= 400:
            return False, None, f"HTTP {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            payload = {"text": response.text[:300]}
        return True, payload, None
    except Exception as exc:
        return False, None, str(exc)


def _processes_by_name(name: str) -> list[psutil.Process]:
    found: list[psutil.Process] = []
    for process in psutil.process_iter(["pid", "name", "exe", "cmdline", "cwd"]):
        try:
            if (process.info.get("name") or "").lower() == name.lower():
                found.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _bridge_processes() -> list[psutil.Process]:
    bridge_root = (Path(settings.torum_root) / "services" / "mt5_bridge").resolve()
    found: list[psutil.Process] = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
        try:
            cmdline = " ".join(process.info.get("cmdline") or [])
            cwd = process.info.get("cwd")
            cwd_path = Path(cwd).resolve() if cwd else None
            if "bridge.main" in cmdline and (cwd_path == bridge_root or str(bridge_root) in cmdline):
                found.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return found


def _terminate_processes(processes: list[psutil.Process], timeout: float = 8.0) -> None:
    for process in processes:
        try:
            logger.info("Terminating process pid=%s name=%s", process.pid, process.name())
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            logger.warning("Could not terminate pid=%s: %s", getattr(process, "pid", "?"), exc)
    gone, alive = psutil.wait_procs(processes, timeout=timeout)
    for process in alive:
        try:
            logger.warning("Killing process pid=%s name=%s", process.pid, process.name())
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            logger.warning("Could not kill pid=%s: %s", getattr(process, "pid", "?"), exc)
    if gone:
        logger.info("Stopped %s process(es)", len(gone))


def _run(args: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    logger.info("Running command: %s cwd=%s", " ".join(args), cwd)
    completed = subprocess.run(args, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout, check=False)
    output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
    if completed.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed ({completed.returncode}): {output[-1000:]}")
    return output[-3000:]


def _docker_compose_args(*args: str) -> list[str]:
    compose_file = Path(settings.docker_compose_file)
    if not compose_file.is_absolute():
        compose_file = Path(settings.torum_root) / compose_file
    return ["docker", "compose", "-f", str(compose_file), *args]


def _start_process(args: list[str], cwd: Path | None = None) -> None:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(args, cwd=str(cwd) if cwd else None, creationflags=creationflags)


def _start_configured_command(command: str, cwd: Path) -> None:
    if os.name == "nt":
        _start_process(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], cwd=cwd)
    else:
        _start_process(["sh", "-lc", command], cwd=cwd)


def check_status() -> SystemStatus:
    items: list[StatusItem] = []
    account_mode = "UNKNOWN"
    last_tick_at: datetime | None = None
    last_tick_age_seconds: int | None = None

    mt5_processes = _processes_by_name(settings.mt5_process_name)
    items.append(
        _item(
            "mt5",
            "MT5 terminal",
            "OK" if mt5_processes else "FAIL",
            f"{len(mt5_processes)} proceso(s)" if mt5_processes else "terminal no encontrado",
            {"pids": [process.pid for process in mt5_processes]},
        )
    )

    bridge_ok, bridge_payload, bridge_error = _http_json(settings.bridge_health_url)
    bridge_processes = _bridge_processes()
    if bridge_ok:
        bridge_status: ComponentStatus = "OK" if bridge_payload and bridge_payload.get("connected_to_mt5", False) else "WARN"
        bridge_message = "bridge vivo" if bridge_status == "OK" else "bridge vivo, MT5 pendiente"
    elif bridge_processes:
        bridge_status = "WARN"
        bridge_message = f"proceso vivo, health falla: {bridge_error}"
    else:
        bridge_status = "FAIL"
        bridge_message = bridge_error or "bridge no encontrado"
    items.append(
        _item(
            "bridge",
            "mt5_bridge",
            bridge_status,
            bridge_message,
            {"health": bridge_payload or {}, "pids": [process.pid for process in bridge_processes]},
        )
    )

    api_ok, api_payload, api_error = _http_json(settings.api_health_url)
    items.append(_item("api", "API/backend", "OK" if api_ok else "FAIL", "backend responde" if api_ok else api_error or "sin respuesta", api_payload or {}))

    frontend_ok, _, frontend_error = _http_json(settings.frontend_health_url)
    items.append(_item("frontend", "frontend", "OK" if frontend_ok else "WARN", "frontend responde" if frontend_ok else frontend_error or "sin respuesta"))

    try:
        docker_output = _run(_docker_compose_args("ps"), cwd=Path(settings.torum_root), timeout=15)
        docker_status: ComponentStatus = "OK"
        docker_message = "docker compose responde"
    except Exception as exc:
        docker_output = str(exc)
        docker_status = "FAIL"
        docker_message = "docker compose falla"
    items.append(_item("docker", "Docker", docker_status, docker_message, {"tail": docker_output[-1000:]}))

    db_status: ComponentStatus = "UNKNOWN"
    redis_status: ComponentStatus = "UNKNOWN"
    db_message = "sin datos"
    redis_message = "sin datos"
    if docker_status == "OK":
        lower = docker_output.lower()
        db_status = "OK" if "timescaledb" in lower and ("healthy" in lower or "running" in lower or "up" in lower) else "WARN"
        redis_status = "OK" if "redis" in lower and ("healthy" in lower or "running" in lower or "up" in lower) else "WARN"
        db_message = "contenedor visible" if db_status == "OK" else "contenedor no confirmado"
        redis_message = "contenedor visible" if redis_status == "OK" else "contenedor no confirmado"
    items.append(_item("db", "DB", db_status, db_message))
    items.append(_item("redis", "Redis", redis_status, redis_message))

    mt5_api_ok, mt5_payload, mt5_error = _http_json(settings.api_mt5_status_url)
    if mt5_api_ok and mt5_payload:
        account_mode = str(mt5_payload.get("account_trade_mode") or "UNKNOWN")
        raw_ticks = mt5_payload.get("last_tick_time_by_symbol") or {}
        parsed_ticks: list[datetime] = []
        if isinstance(raw_ticks, dict):
            for raw_time in raw_ticks.values():
                if isinstance(raw_time, str):
                    try:
                        parsed_ticks.append(datetime.fromisoformat(raw_time.replace("Z", "+00:00")).astimezone(UTC))
                    except ValueError:
                        continue
        if parsed_ticks:
            last_tick_at = max(parsed_ticks)
            last_tick_age_seconds = max(0, int((utcnow() - last_tick_at).total_seconds()))
        mt5_connected = bool(mt5_payload.get("connected_to_mt5"))
        bridge_connected = bool(mt5_payload.get("connected_to_backend"))
        if last_tick_age_seconds is None:
            tick_status = "WARN" if mt5_connected and bridge_connected and api_ok else "FAIL"
            tick_message = "sin ticks. mercado cerrado o esperando datos" if tick_status == "WARN" else "sin ticks y conexion incompleta"
        elif last_tick_age_seconds > settings.max_tick_age_seconds:
            tick_status = "WARN" if mt5_connected and bridge_connected and api_ok else "FAIL"
            tick_message = f"ticks viejos ({last_tick_age_seconds}s). mercado cerrado probable" if tick_status == "WARN" else f"ticks viejos ({last_tick_age_seconds}s)"
        else:
            tick_status = "OK"
            tick_message = f"ultimo tick hace {last_tick_age_seconds}s"
        details = {
            "last_tick_time_by_symbol": raw_ticks,
            "account_trade_mode": account_mode,
            "connected_to_mt5": mt5_connected,
            "connected_to_backend": bridge_connected,
        }
    else:
        tick_status = "FAIL"
        tick_message = mt5_error or "no se pudo leer estado MT5 desde API"
        details = {}
    items.append(_item("ticks", "Ultimos ticks", tick_status, tick_message, details))

    fail_count = sum(1 for item in items if item.status == "FAIL")
    warn_count = sum(1 for item in items if item.status == "WARN")
    overall: ComponentStatus = "FAIL" if fail_count else "WARN" if warn_count else "OK"
    message = "Fallo de conexion" if overall == "FAIL" else "Mercado cerrado o aviso" if overall == "WARN" else "Todo OK"
    return SystemStatus(
        status=overall,
        message=message,
        items=items,
        account_mode=account_mode,
        last_tick_at=last_tick_at,
        last_tick_age_seconds=last_tick_age_seconds,
        action_running=restart_lock.locked(),
        actions=list(actions.values())[-10:],
    )


def _record_action(action_id: str, target: RestartTarget, action_status: str, log_tail: str = "") -> None:
    actions[action_id] = {
        "action_id": action_id,
        "target": target,
        "status": action_status,
        "updated_at": utcnow().isoformat(),
        "log_tail": log_tail[-3000:],
    }


def restart_mt5() -> str:
    _terminate_processes(_processes_by_name(settings.mt5_process_name))
    time.sleep(2)
    if not settings.mt5_path:
        raise RuntimeError("MT5_PATH no configurado")
    mt5_path = Path(settings.mt5_path)
    if not mt5_path.exists():
        raise RuntimeError(f"MT5_PATH no existe: {mt5_path}")
    _start_process([str(mt5_path)])
    time.sleep(settings.startup_delay_seconds)
    if not _processes_by_name(settings.mt5_process_name):
        raise RuntimeError("MT5 no arranco")
    return "MT5 reiniciado"


def restart_bridge() -> str:
    _terminate_processes(_bridge_processes())
    time.sleep(2)
    bridge_root = Path(settings.torum_root) / "services" / "mt5_bridge"
    if settings.bridge_start_cmd:
        _start_configured_command(settings.bridge_start_cmd, bridge_root)
    else:
        _start_process([settings.bridge_python, "-m", "bridge.main"], cwd=bridge_root)
    time.sleep(settings.startup_delay_seconds)
    ok, payload, error = _http_json(settings.bridge_health_url, timeout=5)
    if not ok:
        raise RuntimeError(f"bridge reiniciado pero health falla: {error}")
    return json.dumps(payload or {"ok": True}, ensure_ascii=True)


def restart_api() -> str:
    root = Path(settings.torum_root)
    output = []
    for args in [
        _docker_compose_args("stop", "api"),
        _docker_compose_args("rm", "-f", "api"),
        _docker_compose_args("build", "api"),
        _docker_compose_args("up", "-d", "api"),
    ]:
        output.append(_run(args, cwd=root, timeout=300))
    return "\n".join(output)


def restart_frontend() -> str:
    root = Path(settings.torum_root)
    if settings.frontend_start_cmd:
        _start_configured_command(settings.frontend_start_cmd, root)
        return "frontend start cmd lanzado"
    output = []
    for args in [
        _docker_compose_args("stop", "frontend"),
        _docker_compose_args("build", "frontend"),
        _docker_compose_args("up", "-d", "frontend"),
    ]:
        try:
            output.append(_run(args, cwd=root, timeout=300))
        except Exception as exc:
            raise RuntimeError("No hay servicio frontend en docker. Configura FRONTEND_START_CMD.") from exc
    return "\n".join(output)


def restart_all() -> str:
    logs = []
    for label, func in [("api", restart_api), ("frontend", restart_frontend), ("mt5", restart_mt5), ("bridge", restart_bridge)]:
        try:
            logs.append(f"[{label}] {func()}")
        except Exception as exc:
            logs.append(f"[{label}] ERROR {exc}")
            if label in {"api", "mt5", "bridge"}:
                raise RuntimeError("\n".join(logs)) from exc
    return "\n".join(logs)


def restart_pc() -> str:
    if os.name != "nt":
        raise RuntimeError("Reinicio PC solo soportado en Windows")
    _run(["shutdown", "/r", "/t", "5"], timeout=10)
    return "Reinicio de PC lanzado"


def _perform_restart(action_id: str, target: RestartTarget) -> None:
    try:
        funcs = {
            "mt5": restart_mt5,
            "api": restart_api,
            "frontend": restart_frontend,
            "bridge": restart_bridge,
            "all": restart_all,
            "pc": restart_pc,
        }
        log_tail = funcs[target]()
        _record_action(action_id, target, "OK", log_tail)
    except Exception as exc:
        logger.exception("Restart %s failed", target)
        _record_action(action_id, target, "FAIL", str(exc))
    finally:
        restart_lock.release()


def run_restart(target: RestartTarget) -> dict[str, Any]:
    action_id = str(uuid4())
    if not restart_lock.acquire(blocking=False):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya hay un reinicio en curso")
    _record_action(action_id, target, "RESTARTING")
    thread = threading.Thread(target=_perform_restart, args=(action_id, target), name=f"restart-{target}", daemon=True)
    thread.start()
    return actions[action_id]


app = FastAPI(title="Torum Local Watchdog", version="0.1.0")


@app.get("/health")
def health(_: None = Depends(require_token)) -> dict[str, object]:
    return {"ok": True, "service": "torum-watchdog"}


@app.get("/status", response_model=SystemStatus)
def status_read(_: None = Depends(require_token)) -> SystemStatus:
    return check_status()


@app.post("/restart/{target}")
def restart(target: RestartTarget, payload: RestartRequest, _: None = Depends(require_token)) -> dict[str, Any]:
    expected = "REINICIAR PC" if target == "pc" else "REINICIAR"
    if payload.confirmation.strip().upper() != expected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Confirmacion requerida: {expected}")
    return run_restart(target)
