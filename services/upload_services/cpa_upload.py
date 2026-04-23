import json
import logging
from typing import List, Tuple
from urllib.parse import quote

from curl_cffi import requests as cffi_requests
from curl_cffi import CurlMime

from domain.accounts import AccountRecord
from domain.upload_channels import UploadChannelRecord
from .base_upload import BaseUploader

logger = logging.getLogger("cpa_upload")

def _normalize_cpa_auth_files_url(api_url: str) -> str:
    normalized = (api_url or "").strip().rstrip("/")
    lower_url = normalized.lower()

    if not normalized:
        return ""

    if lower_url.endswith("/auth-files"):
        return normalized

    if lower_url.endswith("/v0/management") or lower_url.endswith("/management"):
        return f"{normalized}/auth-files"

    if lower_url.endswith("/v0"):
        return f"{normalized}/management/auth-files"

    return f"{normalized}/v0/management/auth-files"

def _build_cpa_headers(api_token: str, content_type: str = None) -> dict:
    headers = {"Authorization": f"Bearer {api_token}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers

class CpaUploader(BaseUploader):
    def test_connection(self, channel: UploadChannelRecord) -> Tuple[bool, str]:
        if not channel.api_url:
            return False, "API URL 不能为空"
        if not channel.api_key:
            return False, "API Key 不能为空"

        test_url = _normalize_cpa_auth_files_url(channel.api_url)
        headers = _build_cpa_headers(channel.api_key)

        try:
            response = cffi_requests.get(
                test_url,
                headers=headers,
                proxies=None,
                timeout=10,
                impersonate="chrome110",
            )
            if response.status_code == 200:
                return True, "CPA 连接测试成功"
            if response.status_code == 401:
                return False, "连接成功，但 API Token 无效"
            if response.status_code == 403:
                return False, "连接成功，但服务端未启用远程管理或本Token无权限"
            if response.status_code == 404:
                return False, "未找到 CPA auth-files 接口，请检查地址是否正确"
            if response.status_code == 503:
                return False, "连接成功，但服务端认证管理器不可用"

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
        results = {"success_count": 0, "failed_count": 0, "skipped_count": 0, "details": []}
        if not accounts:
            return results

        upload_url = _normalize_cpa_auth_files_url(channel.api_url)
        
        for acc in accounts:
            if not acc.primary_token:
                results["skipped_count"] += 1
                results["details"].append({"id": acc.id, "email": acc.email, "success": False, "error": "缺少 primary_token"})
                continue

            token_data = {
                "type": "codex",
                "email": acc.email,
                "expired": "",  # CPA 侧目前不强制过期时间处理逻辑，可以忽略
                "id_token": "",
                "account_id": acc.user_id or "",
                "access_token": acc.primary_token,
                "last_refresh": "",
                "refresh_token": acc.password or "",
            }

            filename = f"{acc.email}.json"
            file_content = json.dumps(token_data, ensure_ascii=False, indent=2).encode("utf-8")

            success, msg = self._do_upload_single(upload_url, filename, file_content, channel.api_key)
            if success:
                results["success_count"] += 1
            else:
                results["failed_count"] += 1
                
            results["details"].append({"id": acc.id, "email": acc.email, "success": success, "error" if not success else "message": msg})

        return results

    def _do_upload_single(self, upload_url: str, filename: str, file_content: bytes, api_key: str) -> Tuple[bool, str]:
        # 先尝试 Multipart 
        try:
            mime = CurlMime()
            mime.addpart(name="file", data=file_content, filename=filename, content_type="application/json")
            response = cffi_requests.post(
                upload_url, multipart=mime, headers=_build_cpa_headers(api_key), proxies=None, timeout=30, impersonate="chrome110"
            )
            if response.status_code in (200, 201):
                return True, "上传成功"
            
            if response.status_code in (404, 405, 415):
                # Fallback to pure payload
                raw_url = f"{upload_url}?name={quote(filename)}"
                res2 = cffi_requests.post(
                    raw_url, data=file_content, headers=_build_cpa_headers(api_key, "application/json"), proxies=None, timeout=30, impersonate="chrome110"
                )
                if res2.status_code in (200, 201):
                    return True, "上传成功"
                response = res2

            error_msg = f"HTTP {response.status_code}"
            try:
                detail = response.json()
                error_msg = detail.get("message", error_msg) if isinstance(detail, dict) else error_msg
            except:
                pass
            return False, f"上传失败: {error_msg}"
            
        except Exception as e:
            return False, f"异常: {str(e)}"
