import logging
from datetime import datetime, timezone
from typing import List, Tuple

from curl_cffi import requests as cffi_requests

from domain.accounts import AccountRecord
from domain.upload_channels import UploadChannelRecord
from .base_upload import BaseUploader

logger = logging.getLogger("sub2api_upload")


class Sub2ApiUploader(BaseUploader):
    def test_connection(self, channel: UploadChannelRecord) -> Tuple[bool, str]:
        if not channel.api_url:
            return False, "API URL 不能为空"
        if not channel.api_key:
            return False, "API Key 不能为空"

        url = channel.api_url.rstrip("/") + "/api/v1/admin/accounts/data"
        headers = {"x-api-key": channel.api_key}

        try:
            response = cffi_requests.get(
                url,
                headers=headers,
                proxies=None,
                timeout=10,
                impersonate="chrome110",
            )
            if response.status_code in (200, 201, 204, 405):
                return True, "Sub2API 连接测试成功"
            if response.status_code == 401:
                return False, "连接成功，但 API Key 无效"
            if response.status_code == 403:
                return False, "连接成功，但权限不足"
            return False, f"服务器返回异常状态码: {response.status_code}"
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
        results = {
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "details": []
        }

        if not accounts:
            return results

        if not channel.api_url or not channel.api_key:
            for acc in accounts:
                results["failed_count"] += 1
                results["details"].append({"id": acc.id, "email": acc.email, "success": False, "error": "通道配置无效"})
            return results

        exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        account_items = []
        valid_accounts = []

        for acc in accounts:
            if not acc.primary_token:
                results["skipped_count"] += 1
                results["details"].append({"id": acc.id, "email": acc.email, "success": False, "error": "缺少 primary_token"})
                continue
            
            # Note: Trial end time needs fixing semantics or passed as unix stamp. Defaulting to 0.
            expires_at = acc.trial_end_time if acc.trial_end_time else 0
            
            account_items.append({
                "name": acc.email,
                "platform": acc.platform,
                "type": "oauth",
                "credentials": {
                    "access_token": acc.primary_token,
                    "chatgpt_account_id": acc.user_id or "",
                    "chatgpt_user_id": "",
                    "client_id": "",
                    "expires_at": expires_at,
                    "expires_in": 863999,
                    "model_mapping": {
                        "gpt-5.1": "gpt-5.1",
                        "gpt-5.1-codex": "gpt-5.1-codex",
                        "gpt-5.1-codex-max": "gpt-5.1-codex-max",
                        "gpt-5.1-codex-mini": "gpt-5.1-codex-mini",
                        "gpt-5.2": "gpt-5.2",
                        "gpt-5.2-codex": "gpt-5.2-codex",
                        "gpt-5.3": "gpt-5.3",
                        "gpt-5.3-codex": "gpt-5.3-codex",
                        "gpt-5.4": "gpt-5.4"
                    },
                    "refresh_token": acc.password or "",  # Fallback for old accounts mapping
                },
                "extra": {},
                "concurrency": concurrency,
                "priority": priority,
                "rate_multiplier": 1,
                "auto_pause_on_expired": True,
            })
            valid_accounts.append(acc)

        if not account_items:
            return results

        # newapi 或者 sub2api mapping
        c_type = "newapi-data" if "newapi" in channel.channel_type.lower() else "sub2api-data"
        payload = {
            "data": {
                "type": c_type,
                "version": 1,
                "exported_at": exported_at,
                "proxies": [],
                "accounts": account_items,
            },
            "skip_default_group_bind": True,
        }

        url = channel.api_url.rstrip("/") + "/api/v1/admin/accounts/data"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": channel.api_key,
            "Idempotency-Key": f"import-aar-{exported_at}",
        }

        try:
            response = cffi_requests.post(
                url, json=payload, headers=headers, proxies=None, timeout=30, impersonate="chrome110"
            )

            if response.status_code in (200, 201):
                msg = f"成功上传 {len(account_items)} 个账号"
                for acc in valid_accounts:
                    results["success_count"] += 1
                    results["details"].append({"id": acc.id, "email": acc.email, "success": True, "message": msg})
            else:
                error_msg = f"上传失败: HTTP {response.status_code}"
                try:
                    detail = response.json()
                    if isinstance(detail, dict):
                        error_msg = detail.get("message", error_msg)
                except Exception:
                    error_msg = f"{error_msg} - {response.text[:200]}"
                
                for acc in valid_accounts:
                    results["failed_count"] += 1
                    results["details"].append({"id": acc.id, "email": acc.email, "success": False, "error": error_msg})

        except Exception as e:
            logger.error(f"Sub2API 上传异常: {e}")
            error_msg = f"上传异常: {str(e)}"
            for acc in valid_accounts:
                results["failed_count"] += 1
                results["details"].append({"id": acc.id, "email": acc.email, "success": False, "error": error_msg})

        return results
