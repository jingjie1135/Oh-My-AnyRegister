"""内置 Provider 模板种子数据。"""

# 验证码驱动定义
CAPTCHA_SEEDS = [
    {
        "provider_type": "captcha",
        "provider_key": "local_solver",
        "label": "本地 Turnstile 求解器",
        "driver_type": "local_solver",
        "fields": [
            {"key": "solver_url", "label": "求解器地址 (Camoufox)", "type": "text", "category": "config", "default": "http://localhost:8000/solve"},
        ],
        "is_builtin": True
    },
    {
        "provider_type": "captcha",
        "provider_key": "yescaptcha",
        "label": "YesCaptcha",
        "driver_type": "yescaptcha_api",
        "fields": [
            {"key": "yescaptcha_key", "label": "Client Key", "type": "password", "category": "auth"},
        ],
        "is_builtin": True
    },
    {
        "provider_type": "captcha",
        "provider_key": "twocaptcha",
        "label": "2Captcha",
        "driver_type": "twocaptcha_api",
        "fields": [
            {"key": "twocaptcha_key", "label": "API Key", "type": "password", "category": "auth"},
        ],
        "is_builtin": True
    },
    {
        "provider_type": "captcha",
        "provider_key": "manual",
        "label": "手动输入",
        "driver_type": "manual",
        "fields": [],
        "is_builtin": True
    },
]

# 邮箱驱动定义
MAILBOX_SEEDS = [
    {
        "provider_type": "mailbox",
        "provider_key": "tempmail_lol",
        "label": "TempMail.lol (自动生成)",
        "driver_type": "tempmail_lol_api",
        "fields": [],
        "is_builtin": True
    },
    {
        "provider_type": "mailbox",
        "provider_key": "aitre",
        "label": "Aitre.cc (固定邮箱)",
        "driver_type": "aitre_api",
        "fields": [
            {"key": "aitre_email", "label": "邮箱地址", "type": "text", "category": "config"},
        ],
        "is_builtin": True
    },
    {
        "provider_type": "mailbox",
        "provider_key": "laoudo",
        "label": "Laoudo (对接 API)",
        "driver_type": "laoudo_api",
        "fields": [
            {"key": "laoudo_auth", "label": "Auth Token", "type": "password", "category": "auth"},
            {"key": "laoudo_email", "label": "固定邮箱 (可选)", "type": "text", "category": "config"},
            {"key": "laoudo_account_id", "label": "账号 ID", "type": "text", "category": "config"},
        ],
        "is_builtin": True
    },
    {
        "provider_type": "mailbox",
        "provider_key": "cfworker",
        "label": "Cloudflare Worker (自建)",
        "driver_type": "cfworker_admin_api",
        "fields": [
            {"key": "cfworker_api_url", "label": "API 地址", "type": "text", "category": "config"},
            {"key": "cfworker_admin_token", "label": "管理 Token", "type": "password", "category": "auth"},
            {"key": "cfworker_domain", "label": "指定域名", "type": "text", "category": "config"},
        ],
        "is_builtin": True
    },
    {
        "provider_type": "mailbox",
        "provider_key": "private_api",
        "label": "私人邮箱接口 (自建 API)",
        "driver_type": "private_api",
        "fields": [
            {"key": "private_api_url", "label": "API 地址", "type": "text", "category": "config"},
            {"key": "private_api_admin_email", "label": "管理员邮箱", "type": "text", "category": "auth"},
            {"key": "private_api_admin_password", "label": "管理员密码", "type": "password", "category": "auth"},
            {"key": "private_api_domain", "label": "指定域名", "type": "text", "category": "config"},
        ],
        "is_builtin": True
    },
]

# SMS 驱动定义
SMS_SEEDS = [
    {
        "provider_type": "sms",
        "provider_key": "sms_activate",
        "label": "SMS-Activate.org",
        "driver_type": "sms_activate_api",
        "fields": [
            {"key": "sms_activate_key", "label": "API Key", "type": "password", "category": "auth"},
        ],
        "is_builtin": True
    },
    {
        "provider_type": "sms",
        "provider_key": "herosms",
        "label": "HeroSMS",
        "driver_type": "herosms_api",
        "fields": [
            {"key": "herosms_key", "label": "API Key", "type": "password", "category": "auth"},
        ],
        "is_builtin": True
    },
]

ALL_SEEDS = CAPTCHA_SEEDS + MAILBOX_SEEDS + SMS_SEEDS
