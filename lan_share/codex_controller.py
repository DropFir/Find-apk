from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from typing import Any


DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_EFFORT = "max"
CAPACITY_FALLBACKS = {
    "gpt-5.6-luna": ("gpt-5.6-sol", "low"),
    "gpt-5.6-sol": ("gpt-5.6-terra", "medium"),
}
MAX_WORKERS = 4


@dataclass
class ControllerSettings:
    enabled: bool = False
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    interval_minutes: int = 30
    batch_size: int = 5
    workers: int = 4


@dataclass
class WorkerState:
    worker_id: str
    status: str = "idle"
    thread_id: str | None = None
    turn_id: str | None = None
    active_model: str | None = None
    active_effort: str | None = None
    detail: str = "等待启动"
    stream: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None


class CodexController:
    """Keep a local-only Codex app-server behind the Find APK web console."""

    def __init__(self, project_root: Path, state_path: Path) -> None:
        self.project_root = project_root.resolve()
        self.state_path = state_path
        self._lock = threading.RLock()
        self._writer_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._responses: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._request_id = 0
        self._last_error: str | None = None
        self._last_run_at: float | None = None
        self._next_run_at: float | None = None
        self._batch_remaining = 0
        self.settings = self._load_settings()
        self.workers = {
            f"lan-codex-{index}": WorkerState(f"lan-codex-{index}")
            for index in range(1, MAX_WORKERS + 1)
        }

    def _load_settings(self) -> ControllerSettings:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return ControllerSettings()
        try:
            return ControllerSettings(
                enabled=bool(payload.get("enabled", False)),
                model=self._clean_model(payload.get("model", DEFAULT_MODEL)),
                effort=self._clean_effort(payload.get("effort", DEFAULT_EFFORT)),
                interval_minutes=self._bounded_int(
                    payload.get("interval_minutes", 30), 10, 720
                ),
                batch_size=self._bounded_int(payload.get("batch_size", 5), 1, 10),
                workers=self._bounded_int(
                    payload.get("workers", MAX_WORKERS), 1, MAX_WORKERS
                ),
            )
        except (TypeError, ValueError):
            return ControllerSettings()

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int) -> int:
        number = int(value)
        if number < minimum or number > maximum:
            raise ValueError("setting out of range")
        return number

    @staticmethod
    def _clean_model(value: Any) -> str:
        model = str(value).strip()
        if not model or len(model) > 80 or not all(
            char.isalnum() or char in "._-" for char in model
        ):
            raise ValueError("invalid model")
        return model

    @staticmethod
    def _clean_effort(value: Any) -> str:
        effort = str(value).strip().lower()
        if effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("invalid effort")
        return effort

    def _save_settings(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(self.settings), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.settings = ControllerSettings(
                enabled=bool(payload.get("enabled", self.settings.enabled)),
                model=self._clean_model(payload.get("model", self.settings.model)),
                effort=self._clean_effort(payload.get("effort", self.settings.effort)),
                interval_minutes=self._bounded_int(
                    payload.get("interval_minutes", self.settings.interval_minutes),
                    10,
                    720,
                ),
                batch_size=self._bounded_int(
                    payload.get("batch_size", self.settings.batch_size), 1, 10
                ),
                workers=self._bounded_int(
                    payload.get("workers", self.settings.workers), 1, MAX_WORKERS
                ),
            )
            self._next_run_at = (
                time.time() + self.settings.interval_minutes * 60
                if self.settings.enabled
                else None
            )
            self._save_settings()
        return self.snapshot()

    def _find_command(self) -> str | None:
        configured = os.environ.get("FIND_APK_CODEX_BIN", "").strip()
        if configured:
            return configured if Path(configured).is_file() else None
        command = shutil.which("codex")
        if command:
            return command
        desktop_command = Path(
            "/Applications/ChatGPT.app/Contents/Resources/codex"
        )
        if desktop_command.is_file():
            return str(desktop_command)
        return None

    def _command(self) -> str:
        command = self._find_command()
        if not command:
            raise RuntimeError("本机没有找到 Codex 命令行")
        return command

    def _ensure_server(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            self._responses.clear()
            self._process = subprocess.Popen(
                [self._command(), "app-server", "--listen", "stdio://"],
                cwd=self.project_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            self._reader = threading.Thread(
                target=self._read_messages,
                name="find-apk-codex-reader",
                daemon=True,
            )
            self._reader.start()
        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "find_apk_lan_controller",
                    "title": "Find APK LAN Controller",
                    "version": "1.0",
                }
            },
        )
        self._notify("initialized", {})

    def _read_messages(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = message.get("id")
            if isinstance(request_id, int):
                with self._lock:
                    response = self._responses.get(request_id)
                if response is not None:
                    response.put(message)
                continue
            self._handle_event(message)
        with self._lock:
            if self._process is process:
                self._last_error = "Codex App Server 已停止"
                for worker in self.workers.values():
                    if worker.status in {"starting", "running"}:
                        worker.status = "error"
                        worker.detail = self._last_error
                        worker.turn_id = None
                        worker.finished_at = time.time()

    def _handle_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params") or {}
        if method == "turn/completed":
            turn = params.get("turn") or {}
            turn_id = turn.get("id")
            next_worker: WorkerState | None = None
            capacity_retry: tuple[WorkerState, str, str] | None = None
            completed_thread_id: str | None = None
            with self._lock:
                for worker in self.workers.values():
                    if worker.turn_id != turn_id:
                        continue
                    completed_thread_id = worker.thread_id
                    worker.finished_at = time.time()
                    worker.status = "idle"
                    worker.turn_id = None
                    if self._capacity_limited(worker, turn):
                        fallback = CAPACITY_FALLBACKS.get(worker.active_model or "")
                        if fallback is not None:
                            fallback_model, fallback_effort = fallback
                            fallback_name = (
                                "Sol 轻度"
                                if fallback_model == "gpt-5.6-sol"
                                else "Terra 中等"
                            )
                            worker.detail = f"当前模型满载，正在切换 {fallback_name}"
                            self._append_stream(
                                worker,
                                f"当前模型容量已满，自动切换 {fallback_name} 恢复同一关键词。",
                            )
                            capacity_retry = (
                                worker,
                                fallback_model,
                                fallback_effort,
                            )
                        else:
                            worker.status = "error"
                            worker.detail = "Luna、Sol 与 Terra 当前均满载，等待下一次自动重试"
                            self._append_stream(worker, worker.detail)
                            self._last_error = worker.detail
                    elif turn.get("status") == "completed":
                        worker.detail = "本轮已完成，等待下一次领取"
                        self._append_stream(worker, "本轮已完成，等待下一次领取。")
                    elif turn.get("status") == "interrupted":
                        worker.detail = "已停止，未完成任务会保留在队列"
                        self._append_stream(worker, "已停止，未完成关键词会保留在队列。")
                    else:
                        error = (turn.get("error") or {}).get("message")
                        worker.detail = error or "本轮执行失败"
                        self._append_stream(worker, worker.detail)
                        self._last_error = worker.detail
                    if (
                        capacity_retry is None
                        and worker.status != "error"
                        and turn.get("status") != "interrupted"
                        and self._batch_remaining > 0
                    ):
                        next_worker = worker
                    break
            if capacity_retry is not None:
                retry_worker, retry_model, retry_effort = capacity_retry
                threading.Thread(
                    target=self._archive_then_start_worker,
                    args=(completed_thread_id, retry_worker),
                    kwargs={
                        "model_override": retry_model,
                        "effort_override": retry_effort,
                    },
                    name=f"find-apk-{retry_worker.worker_id}-capacity-fallback",
                    daemon=True,
                ).start()
            elif next_worker is not None:
                # Responses are consumed by this reader thread. Starting the
                # next turn synchronously here would make _request() wait for a
                # response that this same blocked reader must deliver.
                threading.Thread(
                    target=self._archive_then_start_next_worker,
                    args=(completed_thread_id, next_worker),
                    name=f"find-apk-{next_worker.worker_id}-next",
                    daemon=True,
                ).start()
            elif completed_thread_id is not None:
                threading.Thread(
                    target=self._archive_thread,
                    args=(completed_thread_id, worker),
                    name=f"find-apk-{worker.worker_id}-archive",
                    daemon=True,
                ).start()
            return
        if method == "item/agentMessage/delta":
            thread_id = params.get("threadId")
            delta = str(params.get("delta") or "").strip()
            if not delta:
                return
            with self._lock:
                for worker in self.workers.values():
                    if worker.thread_id == thread_id and worker.status == "running":
                        self._append_stream(worker, delta, append_to_last=True)
                        break
            return
        if method in {"item/started", "item/completed"}:
            thread_id = params.get("threadId")
            item = params.get("item") or {}
            activity = self._describe_item_activity(item, completed=method == "item/completed")
            if not activity:
                return
            with self._lock:
                for worker in self.workers.values():
                    if worker.thread_id == thread_id and worker.status == "running":
                        self._append_stream(worker, activity)
                        break
            return
        if method == "warning":
            with self._lock:
                self._last_error = str(params.get("message") or "Codex 发出警告")

    @staticmethod
    def _capacity_limited(worker: WorkerState, turn: dict[str, Any]) -> bool:
        error = (turn.get("error") or {}).get("message") or ""
        recent = " ".join(worker.stream[-6:])
        combined = f"{error} {recent}".casefold()
        return "model is at capacity" in combined

    @staticmethod
    def _describe_item_activity(item: dict[str, Any], *, completed: bool) -> str:
        item_type = str(item.get("type") or "")
        command = " ".join(str(item.get("command") or "").split())
        if item_type in {"commandExecution", "command_execution"}:
            if command:
                prefix = "命令完成：" if completed else "正在执行："
                return f"{prefix}{command[:220]}"
            return "命令执行完成。" if completed else "正在执行本机操作。"
        if item_type in {"webSearch", "web_search"}:
            return "网页查询完成。" if completed else "正在查询网页来源。"
        if item_type in {"fileChange", "file_change"}:
            return "文件处理完成。" if completed else "正在整理下载文件。"
        return ""

    @staticmethod
    def _append_stream(
        worker: WorkerState, message: str, *, append_to_last: bool = False
    ) -> None:
        cleaned = " ".join(str(message).split())
        if not cleaned:
            return
        if append_to_last and worker.stream and worker.stream[-1].startswith("Codex："):
            worker.stream[-1] = (worker.stream[-1] + cleaned)[-800:]
        else:
            prefix = "Codex：" if append_to_last else "进度："
            worker.stream.append(f"{prefix}{cleaned}"[-800:])
        worker.stream[:] = worker.stream[-40:]
        worker.detail = worker.stream[-1][-160:]

    def _send(self, payload: dict[str, Any]) -> None:
        with self._writer_lock:
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                raise RuntimeError("Codex App Server 未运行")
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        with self._lock:
            self._request_id += 1
            request_id = self._request_id
            response: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._responses[request_id] = response
        try:
            self._send({"method": method, "id": request_id, "params": params})
            message = response.get(timeout=timeout)
        except queue.Empty as error:
            raise RuntimeError(f"Codex 未在 {timeout} 秒内响应") from error
        finally:
            with self._lock:
                self._responses.pop(request_id, None)
        if "error" in message:
            detail = message["error"].get("message", "未知错误")
            raise RuntimeError(f"Codex: {detail}")
        return message.get("result") or {}

    def _worker_prompt(self, worker_id: str) -> str:
        return (
            "这是由 Find APK 局域网控制台发起的关键词队列任务。"
            f"你是唯一的 worker：{worker_id}。\n"
            "严格遵守当前仓库 AGENTS.md 的 Find-APK 规则。现在只执行一个独立关键词任务："
            f"运行 tools/keyword_queue.py claim --limit 1 "
            f'--worker "{worker_id}" --automatic，只处理这次领取返回的唯一关键词。\n'
            "若没有领取到任务，直接结束本轮。不得修改局域网网页、服务代码或队列规则；"
            "不得重新领取，也不得启动子任务。完成或按规则标记后结束本轮。"
            "用户未指定安装包格式时，必须先找最新稳定版且可独立安装的 ARM APK；"
            "只有 APK 不存在或校验无效时，才按 XAPK、APKM、APKS 顺序回退。"
            "若任何来源出现 Cloudflare 挑战、403 或真实浏览器后备被策略拦截，"
            "必须按 AGENTS.md 使用本机已配置的 Cloudflare-Faker 后备：先执行"
            "`sh tools/cloudflare_faker.sh check`，通过后调用对应客户端完成当前精确页复核；"
            "不得因为浏览器策略拦截而跳过 Faker。只有 Faker 实际执行并返回可验证失败后，"
            "才能继续下一来源。APKPure 精确 `/download` 页面已经确认应用存在时，若其"
            "`d.apkpure.com` 或 `d.apkpure.net` 文件入口返回 HTML、跳回首页或输出"
            "`browser_download_required`，同一文件入口只执行一次 Faker/Chrome 后备；"
            "后备仍无真实安装包就立即保留已确认身份并轮转到下一个可信来源，不得重复"
            "请求同一 APKPure 链接，也不得把它描述成未找到应用。可以使用 Chrome 做公开页面复核，但不依赖个人账号登录态，"
            "精确候选页仍存在时，Cloudflare、人机验证、403、HTML 响应、Chrome/Faker 超时都不得解除候选锁或执行 miss；"
            "必须保留 candidate_url 并标记 retry。clear-candidate 工具对这类原因会返回 candidate_deferred。"
            "完整来源链路只执行一遍，不得为了累计第二轮无结果而从头重跑。只有明确的"
            "网络超时、连接中断、TLS 或临时 5xx 才对当前请求最多执行两次总尝试；第二次"
            "仍失败就保留准确状态并转到链路中的下一来源。所有启用来源、候选和规定后备"
            "均完成且没有安装包时，执行一次 miss 即结束该关键词。"
            "不修改、关闭或提交用户原有标签页。浏览时只保留本任务新开的最少工作标签；"
            "任务结束前关闭本任务创建的标签，不得关闭用户原有标签。"
        )

    def _start_worker(
        self,
        worker: WorkerState,
        *,
        model_override: str | None = None,
        effort_override: str | None = None,
    ) -> bool:
        if worker.status == "running":
            return False
        active_model = model_override or self.settings.model
        active_effort = effort_override or self.settings.effort
        worker.status = "starting"
        worker.active_model = active_model
        worker.active_effort = active_effort
        worker.detail = "正在连接 Codex…"
        worker.stream.clear()
        self._append_stream(worker, "正在连接 Codex，准备领取关键词。")
        worker.started_at = time.time()
        worker.finished_at = None
        try:
            self._ensure_server()
            thread_result = self._request(
                "thread/start",
                {
                    "model": active_model,
                    "cwd": str(self.project_root),
                    "approvalPolicy": "never",
                    "sandbox": "workspace-write",
                    "serviceName": "find_apk_lan_controller",
                },
                timeout=60,
            )
            worker.thread_id = str(thread_result["thread"]["id"])
            turn_result = self._request(
                "turn/start",
                {
                    "threadId": worker.thread_id,
                    "input": [{"type": "text", "text": self._worker_prompt(worker.worker_id)}],
                    "cwd": str(self.project_root),
                    "approvalPolicy": "never",
                    "sandboxPolicy": {
                        "type": "workspaceWrite",
                        "writableRoots": [str(self.project_root)],
                        "networkAccess": True,
                    },
                    "model": active_model,
                    "effort": active_effort,
                    "summary": "concise",
                },
                timeout=90,
            )
            worker.turn_id = str(turn_result["turn"]["id"])
            worker.status = "running"
            worker.detail = "已领取队列，正在寻找 APK"
            return True
        except (KeyError, RuntimeError, OSError, ValueError) as error:
            worker.status = "error"
            worker.detail = str(error)
            worker.finished_at = time.time()
            self._last_error = worker.detail
            return False

    def _start_next_worker(self, worker: WorkerState) -> bool:
        with self._lock:
            if worker.status != "idle" or self._batch_remaining <= 0:
                return False
            self._batch_remaining -= 1
        return self._start_worker(worker)

    def _archive_thread(
        self, thread_id: str | None, worker: WorkerState | None = None
    ) -> bool:
        if not thread_id:
            return False
        try:
            self._request(
                "thread/archive",
                {"threadId": thread_id},
                timeout=30,
            )
        except (RuntimeError, OSError, ValueError):
            # Archiving is housekeeping. A temporary archive failure must not
            # block the keyword queue or prevent the worker from continuing.
            return False
        if worker is not None:
            with self._lock:
                if worker.thread_id == thread_id and worker.status != "running":
                    worker.thread_id = None
        return True

    def _archive_then_start_worker(
        self,
        thread_id: str | None,
        worker: WorkerState,
        *,
        model_override: str | None = None,
        effort_override: str | None = None,
    ) -> bool:
        self._archive_thread(thread_id, worker)
        return self._start_worker(
            worker,
            model_override=model_override,
            effort_override=effort_override,
        )

    def _archive_then_start_next_worker(
        self, thread_id: str | None, worker: WorkerState
    ) -> bool:
        self._archive_thread(thread_id, worker)
        return self._start_next_worker(worker)

    def run_now(self) -> dict[str, Any]:
        with self._lock:
            if any(worker.status in {"starting", "running"} for worker in self.workers.values()):
                return {"started": 0, **self.snapshot()}
            selected = list(self.workers.values())[: self.settings.workers]
            for worker in selected:
                if worker.status == "error":
                    worker.status = "idle"
                    worker.thread_id = None
                    worker.turn_id = None
                    worker.detail = "准备重新领取关键词"
            self._batch_remaining = self.settings.batch_size
            self._last_run_at = time.time()
            self._last_error = None
        started = sum(1 for worker in selected if self._start_next_worker(worker))
        return {"started": started, **self.snapshot()}

    def tick(self) -> None:
        with self._lock:
            if not self.settings.enabled:
                return
            now = time.time()
            if self._next_run_at is not None and now < self._next_run_at:
                return
            self._next_run_at = now + self.settings.interval_minutes * 60
        self.run_now()

    def stop_running(self) -> dict[str, Any]:
        with self._lock:
            self._batch_remaining = 0
            active = [
                worker
                for worker in self.workers.values()
                if worker.status in {"starting", "running"}
            ]
        for worker in active:
            try:
                self._request(
                    "turn/interrupt",
                    {"threadId": worker.thread_id, "turnId": worker.turn_id},
                    timeout=10,
                )
                worker.detail = "正在停止…"
            except RuntimeError as error:
                worker.status = "error"
                worker.detail = str(error)
                worker.finished_at = time.time()
        # A stopped batch must not leave browser tool sessions behind. The next
        # keyword task starts a fresh App Server and a clean tool context.
        self.shutdown("已停止，未完成任务会保留在队列")
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            process_running = self._process is not None and self._process.poll() is None
            return {
                "available": self._find_command() is not None,
                "server_running": process_running,
                "settings": asdict(self.settings),
                "workers": [asdict(worker) for worker in self.workers.values()],
                "last_error": self._last_error,
                "last_run_at": self._last_run_at,
                "next_run_at": self._next_run_at,
                "batch_remaining": self._batch_remaining,
            }

    def shutdown(self, reason: str = "Codex App Server 已停止") -> None:
        with self._lock:
            process = self._process
            self._process = None
            now = time.time()
            for worker in self.workers.values():
                if worker.status in {"starting", "running"}:
                    worker.status = "error"
                    worker.detail = reason
                    worker.turn_id = None
                    worker.finished_at = now
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
