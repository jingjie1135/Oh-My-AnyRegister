"""Adobe Firefly 平台插件"""
from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registration import BrowserRegistrationAdapter, OtpSpec, RegistrationCapability, RegistrationResult
from core.registry import register
import random

ADOBE_OTP_MAIL_KEYWORD = ""
ADOBE_OTP_CODE_PATTERN = r"(?<!#)(?<!\d)(\d{6})(?!\d)"

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
        extra = result.get("extra", {}) or {}
        subscription = extra.get("subscription") or {}
        status = AccountStatus.REGISTERED
        if subscription.get("success"):
            status = AccountStatus.SUBSCRIBED
        return RegistrationResult(
            email=result["email"],
            password=pwd,
            # 将密码也塞进 Token 里，这样界面的“主凭证”就能直接复制密码
            token=result.get("token", "") or pwd,
            status=status,
            extra=extra
        )

    def _build_subscribe_otp_callback(self, account: Account):
        """为订阅动作构造邮箱验证码回调。"""
        if not self.mailbox:
            return None

        mailbox_info = dict((account.extra or {}).get("verification_mailbox") or {})
        mailbox_account = __import__("core.base_mailbox", fromlist=["MailboxAccount"]).MailboxAccount(
            email=mailbox_info.get("email") or account.email,
            account_id=str(mailbox_info.get("account_id") or ""),
            extra={
                "mailbox_provider_key": mailbox_info.get("provider") or (self.config.extra or {}).get("mail_provider", ""),
                "provider_account": (account.extra or {}).get("provider_account", {}),
                "provider_resource": (account.extra or {}).get("provider_resource", {}),
            },
        )

        def _otp_callback() -> str:
            return self.mailbox.wait_for_code(
                mailbox_account,
                keyword=ADOBE_OTP_MAIL_KEYWORD,
                timeout=120,
                code_pattern=ADOBE_OTP_CODE_PATTERN,
            )

        return _otp_callback

    def _should_auto_subscribe(self) -> bool:
        value = (self.config.extra or {}).get("auto_subscribe")
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    def _load_auto_subscribe_card(self):
        card_id = (self.config.extra or {}).get("card_id")
        if not card_id:
            raise RuntimeError("Adobe 自动订阅已开启，但未配置虚拟卡 card_id")
        try:
            normalized_card_id = int(card_id)
        except (TypeError, ValueError):
            raise RuntimeError("Adobe 自动订阅虚拟卡配置无效") from None

        from core.virtual_card import get_virtual_card

        card = get_virtual_card(normalized_card_id)
        if not card:
            raise RuntimeError("Adobe 自动订阅虚拟卡配置无效")
        return card

    def build_browser_registration_adapter(self):
        auto_subscribe_card = None

        def _build_worker(ctx, artifacts):
            nonlocal auto_subscribe_card
            if self._should_auto_subscribe():
                auto_subscribe_card = self._load_auto_subscribe_card()
                from platforms.adobe.browser_register_subscribe import AdobeBrowserRegisterSubscribe

                return AdobeBrowserRegisterSubscribe(
                    captcha=artifacts.captcha_solver,
                    headless=(ctx.executor_type == "headless"),
                    keep_browser_open=ctx.config.keep_browser_open,
                    proxy=ctx.proxy,
                    otp_callback=artifacts.otp_callback,
                    log_fn=ctx.log,
                    card=auto_subscribe_card,
                )

            from platforms.adobe.browser_register import AdobeBrowserRegister
            return AdobeBrowserRegister(
                captcha=artifacts.captcha_solver,
                headless=(ctx.executor_type == "headless"),
                keep_browser_open=ctx.config.keep_browser_open,
                proxy=ctx.proxy,
                otp_callback=artifacts.otp_callback,
                log_fn=ctx.log,
            )

        def _run_worker(worker, ctx, artifacts):
            if self._should_auto_subscribe():
                return worker.run(
                    email=ctx.identity.email,
                    password=ctx.password or "",
                    card=auto_subscribe_card,
                )
            return worker.run(
                email=ctx.identity.email,
                password=ctx.password or "",
            )

        return BrowserRegistrationAdapter(
            result_mapper=lambda ctx, result: self._map_mailbox_result(result),
            browser_worker_builder=_build_worker,
            browser_register_runner=_run_worker,
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
                {"key": "keep_browser_open", "label": "脚本结束后保留可视浏览器", "type": "checkbox", "required": False},
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
            try:
                normalized_card_id = int(card_id)
            except (TypeError, ValueError):
                return {"ok": False, "data": {"message": "虚拟卡配置无效"}}
            from core.virtual_card import get_virtual_card
            card = get_virtual_card(normalized_card_id)
            if not card:
                return {"ok": False, "data": {"message": "虚拟卡配置无效"}}
            from platforms.adobe.browser_subscribe import AdobeBrowserSubscribe
            worker = AdobeBrowserSubscribe(
                headless=False,
                keep_browser_open=bool(params.get("keep_browser_open") or (self.config.extra or {}).get("keep_browser_open")),
                otp_callback=self._build_subscribe_otp_callback(account),
                log_fn=self.log,
            )
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
