"""Adobe Firefly 平台插件"""
from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registration import BrowserRegistrationAdapter, OtpSpec, RegistrationCapability, RegistrationResult
from core.registry import register
import random

def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"

@register
class AdobePlatform(BasePlatform):
    name = "adobe"
    display_name = "Adobe Firefly"
    version = "1.0.0"
    supported_executors = ["headless", "headed"]
    supported_identity_modes = ["mailbox"]

    def __init__(self, config: RegisterConfig = None, mailbox: BaseMailbox = None):
        super().__init__(config)
        self.mailbox = mailbox

    def _prepare_registration_password(self, password: str | None) -> str | None:
        """确保密码满足 Adobe 要求 (至少10位，包含大小写、数字、符号)"""
        if password and len(password) >= 10:
            return password
            
        import string
        lower = random.choices(string.ascii_lowercase, k=4)
        upper = random.choices(string.ascii_uppercase, k=3)
        digits = random.choices(string.digits, k=2)
        symbols = random.choices("!@#$%&*", k=1)
        chars = lower + upper + digits + symbols
        random.shuffle(chars)
        return "".join(chars)

    def _map_mailbox_result(self, result: dict) -> RegistrationResult:
        """映射注册结果"""
        pwd = result.get("password", "")
        return RegistrationResult(
            email=result["email"],
            password=pwd,
            # 将密码也塞进 Token 里，这样界面的“主凭证”就能直接复制密码
            token=result.get("token", "") or pwd,
            status=AccountStatus.REGISTERED,
            extra=result.get("extra", {})
        )

    def build_browser_registration_adapter(self):
        return BrowserRegistrationAdapter(
            result_mapper=lambda ctx, result: self._map_mailbox_result(result),
            browser_worker_builder=lambda ctx, artifacts: __import__("platforms.adobe.browser_register", fromlist=["AdobeBrowserRegister"]).AdobeBrowserRegister(
                captcha=artifacts.captcha_solver,
                headless=(ctx.executor_type == "headless"),
                proxy=ctx.proxy,
                otp_callback=artifacts.otp_callback,
                log_fn=ctx.log,
            ),
            browser_register_runner=lambda worker, ctx, artifacts: worker.run(
                email=ctx.identity.email,
                password=ctx.password or "",
            ),
            capability=RegistrationCapability(oauth_headless_requires_browser_reuse=False),
            # 指定验证码页面出现时的识别特征
            otp_spec=OtpSpec(wait_message="等待 Adobe 邮箱验证码...", success_label="验证码"),
            use_captcha_for_mailbox=True,
        )

    def check_valid(self, account: Account) -> bool:
        # TODO: 使用 Adobe Token 调用 /api/auth/me 之类的端点来验证可用性
        return True

    def get_platform_actions(self) -> list:
        return [
            {"id": "get_account_state", "label": "查询账号状态", "params": []},
            {"id": "subscribe_pro_plus", "label": "订阅 Pro Plus 试用", "params": [
                {"key": "card_id", "label": "虚拟卡 ID", "type": "number", "required": True},
            ]},
        ]

    def execute_action(self, action_id: str, account: Account, params: dict) -> dict:
        if action_id == "get_account_state":
            return {
                "ok": True,
                "data": {
                    "valid": True,
                    "message": "暂未实现用量查询"
                }
            }
        if action_id == "subscribe_pro_plus":
            # 单账号订阅通过 batch-subscribe API 执行
            card_id = params.get("card_id")
            if not card_id:
                return {"ok": False, "data": {"message": "请提供虚拟卡 ID"}}
            from core.virtual_card import get_virtual_card
            card = get_virtual_card(int(card_id))
            if not card:
                return {"ok": False, "data": {"message": "虚拟卡不存在"}}
            from platforms.adobe.browser_subscribe import AdobeBrowserSubscribe
            worker = AdobeBrowserSubscribe(headless=False)
            result = worker.run(
                email=account.email,
                password=account.password,
                card_number=card.card_number,
                exp_month=card.exp_month,
                exp_year=card.exp_year,
                cvc=card.cvc,
            )
            return {
                "ok": result.success,
                "data": {
                    "message": result.message,
                    "stage": result.stage,
                    "error": result.error,
                }
            }
        raise NotImplementedError(f"未知操作: {action_id}")
