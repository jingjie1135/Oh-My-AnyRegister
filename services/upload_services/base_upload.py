from abc import ABC, abstractmethod
from typing import List, Tuple

from domain.accounts import AccountRecord
from domain.upload_channels import UploadChannelRecord


class BaseUploader(ABC):
    @abstractmethod
    def test_connection(self, channel: UploadChannelRecord) -> Tuple[bool, str]:
        """
        测试连接连通性
        返回: (是否成功, 信息说明)
        """
        pass

    @abstractmethod
    def upload_accounts(
        self,
        channel: UploadChannelRecord,
        accounts: List[AccountRecord],
        concurrency: int = 3,
        priority: int = 50,
    ) -> dict:
        """
        执行批量账号上传
        返回: 必须包含以下字典结构
        {
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "details": [
                {"id": 1, "email": "a@example.com", "success": True, "message": "上传成功", "error": ""}
            ]
        }
        """
        pass
