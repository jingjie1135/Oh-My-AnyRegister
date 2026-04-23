import logging
from typing import List, Tuple

from curl_cffi import requests as cffi_requests

from domain.accounts import AccountRecord
from domain.upload_channels import UploadChannelRecord
from .base_upload import BaseUploader

logger = logging.getLogger("adobe2api_upload")


class Adobe2ApiUploader(BaseUploader):
    def test_connection(self, channel: UploadChannelRecord) -> Tuple[bool, str]:
        if not channel.api_url:
            return False, "API URL 不能为空"
        if not channel.api_key:
            return False, "API Key 不能为空"

        url = channel.api_url.rstrip("/") + "/api/v1/admin/profiles"
        headers = {"Authorization": f"Bearer {channel.api_key}"}

        try:
            resp = cffi_requests.get(
                url,
                headers=headers,
                proxies=None,
                timeout=10,
                impersonate="chrome110",
            )
            if resp.status_code in (200, 204, 405):
                return True, "Adobe2API 连接测试成功"
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

        valid_accounts = []
        batch_items = []

        for account in accounts:
            try:
                # 尝试从凭据池中拿到 cookie
                ck_cred = next((c for c in account.credentials if c.get("credential_type") == "cookie"), None)
                if not ck_cred:
                    results["skipped_count"] += 1
                    results["details"].append(
                        {"id": account.id, "email": account.email, "success": False, "error": "账户无记录 cookie 状态"}
                    )
                    continue

                val = ck_cred.get("value") or ""
                # 如果是字符串的话尝试解析为 JSON 或者直接提交
                
                batch_items.append({
                    "cookie": val,
                    "name": account.email
                })
                valid_accounts.append(account)
            except Exception as e:
                 results["failed_count"] += 1
                 results["details"].append(
                     {"id": account.id, "email": account.email, "success": False, "error": f"解析异常: {str(e)}"}
                 )

        if not valid_accounts:
            return results

        # 考虑到 Adobe2API 的 batch 接口可能叫做 /api/v1/refresh-profiles/import-cookie/batch ，如果不存在则逐个导入
        url_single = channel.api_url.rstrip("/") + "/api/v1/refresh-profiles/import-cookie"
        headers = {
            "Authorization": f"Bearer {channel.api_key}",
            "Content-Type": "application/json",
        }

        for item, acc in zip(batch_items, valid_accounts):
            payload = {
                "cookie": item["cookie"],
                "name": item["name"]
            }
            try:
                resp = cffi_requests.post(
                    url_single,
                    headers=headers,
                    json=payload,
                    proxies=None,
                    timeout=30,
                    impersonate="chrome110",
                )
                if resp.status_code in (200, 201):
                    results["success_count"] += 1
                    results["details"].append(
                        {"id": acc.id, "email": acc.email, "success": True, "message": "Cookie上传并刷新成功"}
                    )
                else:
                    error_msg = f"HTTP {resp.status_code}"
                    try:
                        detail = resp.json()
                        error_msg = detail.get("error", detail.get("detail", error_msg)) if isinstance(detail, dict) else error_msg
                    except Exception:
                        pass
                    results["failed_count"] += 1
                    results["details"].append(
                        {"id": acc.id, "email": acc.email, "success": False, "error": error_msg}
                    )
            except Exception as e:
                results["failed_count"] += 1
                results["details"].append(
                    {"id": acc.id, "email": acc.email, "success": False, "error": str(e)}
                )

        return results
