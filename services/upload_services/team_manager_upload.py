import logging
from typing import List, Tuple

from curl_cffi import requests as cffi_requests

from domain.accounts import AccountRecord
from domain.upload_channels import UploadChannelRecord
from .base_upload import BaseUploader

logger = logging.getLogger("team_manager_upload")


class TeamManagerUploader(BaseUploader):
    def test_connection(self, channel: UploadChannelRecord) -> Tuple[bool, str]:
        if not channel.api_url:
            return False, "API URL 不能为空"
        if not channel.api_key:
            return False, "API Key 不能为空"

        url = channel.api_url.rstrip("/") + "/admin/teams/import"
        headers = {"X-API-Key": channel.api_key}

        try:
            resp = cffi_requests.options(
                url,
                headers=headers,
                proxies=None,
                timeout=10,
                impersonate="chrome110",
            )
            if resp.status_code in (200, 204, 401, 403, 405):
                if resp.status_code == 401:
                    return False, "连接成功，但 API Key 无效"
                return True, "Team Manager 连接测试成功"
            return False, f"服务器返回异常状态码: {resp.status_code}"
        except cffi_requests.exceptions.ConnectionError as e:
            return False, f"无法连接到服务器: {str(e)}"
        except cffi_requests.exceptions.Timeout:
            return False, "连接超时，请检查网络配置"
        except Exception as e:
            return False, f"连接测试失败: {str(e)}"

    def upload_accounts(
        self,
        channel: UploadChannelRecord,
        accounts: List[AccountRecord],
        concurrency: int = 3,
        priority: int = 50,
    ) -> dict:
        results = {"success_count": 0, "failed_count": 0, "skipped_count": 0, "details": []}

        if not accounts:
            return results

        lines = []
        valid_accounts = []
        for account in accounts:
            if not account.primary_token:
                results["skipped_count"] += 1
                results["details"].append(
                    {"id": account.id, "email": account.email, "success": False, "error": "缺少 primary_token"}
                )
                continue
            
            # Format: Email, AccessToken, RefreshToken, SessionToken, ClientID
            pwd = account.password or ""
            # any-auto-register stores everything into one or two specific fields. 
            lines.append(",".join([
                account.email or "",
                account.primary_token or "",
                pwd,  # assuming refresh is fallback to password in any-auto-register
                "",   # SessionToken
                "",   # ClientID
            ]))
            valid_accounts.append(account)

        if not valid_accounts:
            return results

        url = channel.api_url.rstrip("/") + "/admin/teams/import"
        headers = {
            "X-API-Key": channel.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "import_type": "batch",
            "content": "\n".join(lines),
        }

        try:
            resp = cffi_requests.post(
                url,
                headers=headers,
                json=payload,
                proxies=None,
                timeout=60,
                impersonate="chrome110",
            )
            if resp.status_code in (200, 201):
                for account in valid_accounts:
                    results["success_count"] += 1
                    results["details"].append(
                        {"id": account.id, "email": account.email, "success": True, "message": "批量上传成功"}
                    )
            else:
                error_msg = f"批量上传失败: HTTP {resp.status_code}"
                try:
                    detail = resp.json()
                    error_msg = detail.get("message", error_msg) if isinstance(detail, dict) else error_msg
                except Exception:
                    pass
                for account in valid_accounts:
                    results["failed_count"] += 1
                    results["details"].append(
                        {"id": account.id, "email": account.email, "success": False, "error": error_msg}
                    )
        except Exception as e:
            for account in valid_accounts:
                results["failed_count"] += 1
                results["details"].append(
                    {"id": account.id, "email": account.email, "success": False, "error": str(e)}
                )

        return results
