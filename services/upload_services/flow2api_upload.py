import logging
from typing import List, Tuple

from curl_cffi import requests as cffi_requests

from domain.accounts import AccountRecord
from domain.upload_channels import UploadChannelRecord
from .base_upload import BaseUploader

logger = logging.getLogger("flow2api_upload")


class Flow2ApiUploader(BaseUploader):
    def test_connection(self, channel: UploadChannelRecord) -> Tuple[bool, str]:
        if not channel.api_url:
            return False, "API URL 不能为空"
        if not channel.api_key:
            return False, "API Key 不能为空"

        url = channel.api_url.rstrip("/") + "/api/system/info"
        headers = {"Authorization": f"Bearer {channel.api_key}"}

        try:
            resp = cffi_requests.get(
                url,
                headers=headers,
                proxies=None,
                timeout=10,
                impersonate="chrome110",
            )
            if resp.status_code == 200:
                return True, "Flow2API 连接测试成功"
            if resp.status_code == 401:
                return False, "连接成功，但 API Key 无效"
            if resp.status_code == 403:
                return False, "连接成功，但权限不足"
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

        tokens = []
        valid_accounts = []

        for account in accounts:
            if not account.primary_token and not account.password:
                results["skipped_count"] += 1
                results["details"].append(
                    {"id": account.id, "email": account.email, "success": False, "error": "缺少凭据(AccessToken或SessionToken)"}
                )
                continue
            
            # Flow2API 导入支持 st 和 at, any-auto-register 的密码有可能是 session token, primary token 有可能是 access token
            tokens.append({
                "email": account.email,
                "access_token": account.primary_token or "",
                "session_token": account.password or "",  # 使用密码代替
                "is_active": True,
                "image_enabled": True,
                "video_enabled": True,
                "image_concurrency": -1,
                "video_concurrency": -1,
            })
            valid_accounts.append(account)

        if not valid_accounts:
            return results

        url = channel.api_url.rstrip("/") + "/api/tokens/import"
        headers = {
            "Authorization": f"Bearer {channel.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"tokens": tokens}

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
                try:
                    detail = resp.json()
                    added = detail.get("added", 0)
                    updated = detail.get("updated", 0)
                    for account in valid_accounts:
                        results["success_count"] += 1
                        results["details"].append(
                            {"id": account.id, "email": account.email, "success": True, "message": f"批量上传完成，本次批次共新增{added}，更新{updated}"}
                        )
                except Exception:
                    for account in valid_accounts:
                        results["success_count"] += 1
                        results["details"].append(
                            {"id": account.id, "email": account.email, "success": True, "message": "上传成功"}
                        )
            else:
                error_msg = f"上传失败: HTTP {resp.status_code}"
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
