from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from git import Repo
from git.exc import GitCommandError

from services.json_file import read_json_file, write_json_file
from services.storage.base import (
    StorageBackend,
    aggregate_channel_usage_rows,
    is_channel_usage_aggregate_row,
)
from services.storage.channel_usage import match_channel_usage, normalize_channel_usage_entry


class GitStorageBackend(StorageBackend):
    """Git 私有仓库存储后端"""

    def __init__(
        self,
        repo_url: str,
        token: str,
        branch: str = "main",
        file_path: str = "accounts.json",
        auth_keys_file_path: str = "auth_keys.json",
        channel_usage_file_path: str = "channel_usage.json",
        local_cache_dir: Path | None = None,
    ):
        self.repo_url = repo_url
        self.token = token
        self.branch = branch
        self.file_path = file_path
        self.auth_keys_file_path = auth_keys_file_path
        self.channel_usage_file_path = channel_usage_file_path
        self._channel_usage_lock = threading.RLock()

        # 本地缓存目录
        if local_cache_dir is None:
            local_cache_dir = Path(tempfile.gettempdir()) / "chatgpt2api_git_cache"
        self.local_cache_dir = local_cache_dir
        self.local_cache_dir.mkdir(parents=True, exist_ok=True)

        # 构建带认证的 Git URL
        self.auth_repo_url = self._build_auth_url(repo_url, token)

    @staticmethod
    def _build_auth_url(repo_url: str, token: str) -> str:
        """构建带认证的 Git URL"""
        if not token:
            return repo_url
        
        # 支持 HTTPS 格式：https://github.com/user/repo.git
        if repo_url.startswith("https://"):
            # 插入 token
            return repo_url.replace("https://", f"https://{token}@")
        
        # 支持 git@ 格式：git@github.com:user/repo.git
        # 转换为 HTTPS 格式
        if repo_url.startswith("git@"):
            repo_url = repo_url.replace("git@", "https://")
            repo_url = repo_url.replace(".com:", ".com/")
            return repo_url.replace("https://", f"https://{token}@")
        
        return repo_url

    def _clone_or_pull(self) -> Repo:
        """克隆或拉取仓库"""
        repo_path = self.local_cache_dir / "repo"
        
        if repo_path.exists() and (repo_path / ".git").exists():
            # 仓库已存在，拉取最新代码
            try:
                repo = Repo(repo_path)
                origin = repo.remote("origin")
                origin.pull(self.branch)
                return repo
            except GitCommandError:
                # 拉取失败，删除重新克隆
                shutil.rmtree(repo_path)
        
        # 克隆仓库
        repo = Repo.clone_from(
            self.auth_repo_url,
            repo_path,
            branch=self.branch,
        )
        return repo

    def load_accounts(self) -> list[dict[str, Any]]:
        """从 Git 仓库加载账号数据"""
        try:
            return self._load_json_file(self.file_path)
        except Exception as e:
            print(f"[git-storage] load failed: {e}")
            raise

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存账号数据到 Git 仓库"""
        try:
            self._save_json_file(self.file_path, accounts, "Update accounts data")
        except Exception as e:
            print(f"[git-storage] save failed: {e}")
            raise e

    def load_auth_keys(self) -> list[dict[str, Any]]:
        """从 Git 仓库加载鉴权密钥数据"""
        try:
            data = self._load_json_value(self.auth_keys_file_path)
            if isinstance(data, dict):
                data = data.get("items")
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"[git-storage] load failed: {e}")
            raise

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存鉴权密钥数据到 Git 仓库"""
        try:
            self._save_json_file(self.auth_keys_file_path, {"items": auth_keys}, "Update auth keys data")
        except Exception as e:
            print(f"[git-storage] save failed: {e}")
            raise e

    def append_channel_usage(self, entry: dict[str, Any]) -> dict[str, Any]:
        """追加 channel_usage 流水到 Git 仓库中的 channel_usage.json。"""
        normalized = normalize_channel_usage_entry(entry)
        if normalized is None:
            raise ValueError("invalid channel_usage entry")
        with self._channel_usage_lock:
            try:
                items = self._load_json_file(self.channel_usage_file_path)
                items.append(normalized)
                if len(items) > 50000:
                    items = items[-50000:]
                self._save_json_file(
                    self.channel_usage_file_path,
                    items,
                    "Append channel_usage ledger entry",
                )
            except Exception as e:
                print(f"[git-storage] channel_usage append failed: {e}")
                raise e
        return dict(normalized)

    def query_channel_usage(
        self,
        *,
        account_id: str | None = None,
        trace_id: str | None = None,
        channel: str | None = None,
        ts_from: float | None = None,
        ts_to: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._channel_usage_lock:
            try:
                items = self._load_json_file(self.channel_usage_file_path)
            except Exception as e:
                print(f"[git-storage] channel_usage query failed: {e}")
                raise
        matched = [
            dict(item)
            for item in items
            if isinstance(item, dict)
            and match_channel_usage(
                item,
                account_id=account_id,
                trace_id=trace_id,
                channel=channel,
                ts_from=ts_from,
                ts_to=ts_to,
            )
        ]
        matched.sort(key=lambda row: float(row.get("ts") or 0), reverse=True)
        cap = max(1, min(int(limit or 100), 1000))
        return matched[:cap]

    def delete_channel_usage_before(self, ts: float) -> int:
        """删除 ts 之前的明细行；日聚合冷数据永久保留。"""
        cutoff = float(ts)
        with self._channel_usage_lock:
            try:
                items = self._load_json_file(self.channel_usage_file_path)
            except Exception as e:
                print(f"[git-storage] channel_usage delete failed: {e}")
                raise
            kept: list[dict[str, Any]] = []
            deleted = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                if is_channel_usage_aggregate_row(item):
                    kept.append(item)
                    continue
                try:
                    row_ts = float(item.get("ts") or 0)
                except (TypeError, ValueError):
                    row_ts = 0.0
                if row_ts < cutoff:
                    deleted += 1
                    continue
                kept.append(item)
            if deleted:
                try:
                    self._save_json_file(
                        self.channel_usage_file_path,
                        kept,
                        "Prune channel_usage ledger before cutoff",
                    )
                except Exception as e:
                    print(f"[git-storage] channel_usage prune save failed: {e}")
                    raise e
            return deleted

    def aggregate_channel_usage_daily(
        self,
        day_start_ts: float,
        day_end_ts: float,
    ) -> list[dict[str, Any]]:
        with self._channel_usage_lock:
            try:
                items = self._load_json_file(self.channel_usage_file_path)
            except Exception as e:
                print(f"[git-storage] channel_usage aggregate failed: {e}")
                raise
        return aggregate_channel_usage_rows(
            items,
            day_start_ts=day_start_ts,
            day_end_ts=day_end_ts,
        )

    def export_channel_usage(self) -> list[dict[str, Any]]:
        """导出全部 channel_usage 流水（备份用）。"""
        with self._channel_usage_lock:
            try:
                items = self._load_json_file(self.channel_usage_file_path)
            except Exception as e:
                print(f"[git-storage] channel_usage export failed: {e}")
                raise
        return [dict(item) for item in items if isinstance(item, dict)]

    def _load_json_file(self, file_path: str) -> list[dict[str, Any]]:
        data = self._load_json_value(file_path)
        return data if isinstance(data, list) else []

    def _load_json_value(self, file_path: str) -> Any:
        repo = self._clone_or_pull()
        file_full_path = Path(repo.working_dir) / file_path
        if not file_full_path.exists():
            return None
        return read_json_file(file_full_path, name=file_path, default_factory=lambda: None)

    def _save_json_file(self, file_path: str, items: Any, message: str) -> None:
        repo = self._clone_or_pull()
        file_full_path = Path(repo.working_dir) / file_path
        write_json_file(file_full_path, items, backup=False)
        repo.index.add([file_path])
        if repo.is_dirty():
            repo.index.commit(message)
            repo.remote("origin").push(self.branch)

    def health_check(self) -> dict[str, Any]:
        """健康检查"""
        try:
            repo = self._clone_or_pull()
            return {
                "status": "healthy",
                "backend": "git",
                "repo_url": self._mask_token(self.repo_url),
                "branch": self.branch,
                "file_path": self.file_path,
                "auth_keys_file_path": self.auth_keys_file_path,
                "channel_usage_file_path": self.channel_usage_file_path,
                "last_commit": repo.head.commit.hexsha[:8],
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "git",
                "error": str(e),
            }

    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        return {
            "type": "git",
            "description": "Git 私有仓库存储",
            "repo_url": self._mask_token(self.repo_url),
            "branch": self.branch,
            "file_path": self.file_path,
            "auth_keys_file_path": self.auth_keys_file_path,
            "channel_usage_file_path": self.channel_usage_file_path,
        }

    @staticmethod
    def _mask_token(url: str) -> str:
        """隐藏 URL 中的 token"""
        if "@" in url and "://" in url:
            protocol, rest = url.split("://", 1)
            if "@" in rest:
                _, host = rest.split("@", 1)
                return f"{protocol}://****@{host}"
        return url
