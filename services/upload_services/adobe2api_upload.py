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
            return False, "密码/API Key 不能为空"

        url = channel.api_url.rstrip("/") + "/api/v1/auth/login"
        payload = {
            "username": "admin",
            "password": channel.api_key
        }

        try:
            with cffi_requests.Session() as s:
                resp = s.post(
                    url,
                    json=payload,
                    proxies=None,
                    timeout=10,
                    impersonate="chrome110",
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "ok":
                        return True, "Adobe2API 连接及鉴权测试成功"
                return False, "管理员密码错误或连接被拒绝"
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
                ck_cred = None
                for c in account.credentials:
                    key_name = str(c.get("key") or "").lower()
                    if key_name in ("cookie", "cookies", "legacy_token", "session_token"):
                        ck_cred = c
                        break
                
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

        url_login = channel.api_url.rstrip("/") + "/api/v1/auth/login"
        url_single = channel.api_url.rstrip("/") + "/api/v1/refresh-profiles/import-cookie"

        try:
            s = cffi_requests.Session()
            login_resp = s.post(
                url_login,
                json={"username": "admin", "password": channel.api_key},
                timeout=10,
                impersonate="chrome110"
            )
            if login_resp.status_code != 200 or login_resp.json().get("status") != "ok":
                results["failed_count"] += len(valid_accounts)
                results["details"].append({"id": 0, "email": "ALL", "success": False, "error": "后台登录鉴权失效"})
                return results
                
            headers = {
                "Content-Type": "application/json",
            }
            
            for item, acc in zip(batch_items, valid_accounts):
                payload = {
                    "cookie": item["cookie"],
                    "name": item["name"]
                }
                try:
                    resp = s.post(
                        url_single,
                        headers=headers,
                        json=payload,
                        proxies=None,
                        timeout=30,
                    )
                    if resp.status_code in (200, 201):
                        resp_data = resp.json()
                        refresh_err = resp_data.get("refresh_error") or ""
                        status_val = resp_data.get("status", "")
                        # Cookie 已成功入库到 adobe2api，即使即时 refresh 失败也算成功
                        # adobe2api 后台会按照配置的刷新间隔自动重试
                        if status_val == "ok" or resp_data.get("profile"):
                            msg = "Cookie上传并刷新成功"
                            if refresh_err:
                                msg = f"Cookie已入库, 首次刷新待重试: {refresh_err}"
                            results["success_count"] += 1
                            results["details"].append(
                                {"id": acc.id, "email": acc.email, "success": True, "message": msg}
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
        except Exception as exc:
            results["failed_count"] += len(valid_accounts)
            results["details"].append(
                {"id": 0, "email": "ALL", "success": False, "error": f"批量下发会话异常: {str(exc)}"}
            )

        return results
