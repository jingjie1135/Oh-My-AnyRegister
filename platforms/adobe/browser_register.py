import time
import random
import re
import logging
from DrissionPage import ChromiumOptions, ChromiumPage
from fake_useragent import UserAgent

logger = logging.getLogger("adobe_browser")

# ====================== Stealth JS 防风控指纹补丁 ======================
STEALTH_JS = """
// 1. 消除 navigator.webdriver 标志 (最关键!)
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// 2. 修复 window.chrome 对象
if (!window.chrome) {
    window.chrome = {
        runtime: {
            onMessage: { addListener: function() {}, removeListener: function() {} },
            sendMessage: function() {},
        },
    };
}

// 3. 修复 Permissions API (Arkose 检测 notification)
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = function(parameters) {
    if (parameters.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission });
    }
    return originalQuery.call(this, parameters);
};

// 4. 修复 navigator.plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
            { name: 'Chromium PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chromium PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
        ];
        plugins.length = 5;
        return plugins;
    },
    configurable: true,
});

// 5. 修复 navigator.languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
    configurable: true,
});

// 6. 消除 CDP 痕迹
delete window.__cdp_binding__;
delete window.__selenium_unwrapped;
delete window.__driver_evaluate;
delete window.__webdriver_evaluate;

// 7. 消除报错中提取出的 CDP hook 痕迹
const originalError = Error;
const handler = {
    construct: function(target, args) {
        const error = new target(...args);
        if (error.stack) {
            error.stack = error.stack.replace(/Extension|chrome-extension|moz-extension/g, 'https');
        }
        return error;
    }
};

// 8. Canvas 噪声干扰
const originalGetContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(type, attributes) {
    const ctx = originalGetContext.call(this, type, attributes);
    if (type === '2d' && ctx) {
        const origGetImageData = ctx.getImageData;
        ctx.getImageData = function(...args) {
            const imageData = origGetImageData.apply(this, args);
            for (let i = 0; i < imageData.data.length; i += 4) {
                imageData.data[i] ^= 1;  
            }
            return imageData;
        };
    }
    return ctx;
};
"""

class AdobeBrowserRegister:
    """Adobe Browser Register 工作流"""
    
    SIGNUP_URL = (
        "https://auth.services.adobe.com/zh_HANS/deeplink.html"
        "?deeplink=signup"
        "&callback=https://firefly.adobe.com/"
        "&client_id=clio-playground-web"
        "&scope=openid,creative_cloud,creative_sdk,ab.manage"
    )

    def __init__(self, captcha=None, headless: bool = False, proxy: str = None, otp_callback=None, log_fn=None):
        self.captcha = captcha
        self.headless = headless
        self.proxy = proxy
        self._otp_callback = otp_callback
        self.log = log_fn or logger.info
        self.page = None

    def _delay(self, lo=0.5, hi=1.5):
        time.sleep(random.uniform(lo, hi))

    def _gen_profile(self):
        firsts = ["James", "Mary", "John", "Sarah", "Alex", "Emma", "David", "Lisa"]
        lasts = ["Smith", "Johnson", "Brown", "Taylor", "Wilson", "Davis", "Clark"]
        return {
            "fn": random.choice(firsts),
            "ln": random.choice(lasts),
            "month": random.randint(1, 12),
            "year": random.randint(1980, 2002),
        }

    def _wait_page_ready(self, timeout=15):
        start = time.time()
        while time.time() - start < timeout:
            try:
                state = self.page.run_js("document.readyState")
                if state == "complete":
                    time.sleep(0.5)
                    return True
            except:
                pass
            time.sleep(0.5)
        return False

    def _find_and_click(self, texts, timeout=20, label="", tag_filter=None):
        start = time.time()
        while time.time() - start < timeout:
            for txt in texts:
                try:
                    eles = self.page.eles(f'text:{txt}', timeout=1)
                    for ele in eles:
                        try:
                            if tag_filter and ele.tag.lower() not in [t.lower() for t in tag_filter]:
                                continue
                            if ele.states.is_displayed:
                                ele.scroll.to_see()
                                self._delay(0.1, 0.3)
                                ele.click()
                                self.log(f"✅ 点击成功: '{txt}' <{ele.tag}> {f'({label})' if label else ''}")
                                return True
                        except:
                            continue
                except:
                    continue
            self._delay(1, 2)
        return False

    def _safe_type(self, locator, text):
        if isinstance(locator, str):
            target = self.page.ele(locator)
        else:
            target = locator
            
        if target:
            target.click()
            time.sleep(random.uniform(0.3, 0.7))
            target.clear()
            for char in text:
                target.input(char)
                delay = random.uniform(0.02, 0.12)
                if random.random() < 0.08:
                    delay += random.uniform(0.2, 0.5)
                time.sleep(delay)
            time.sleep(random.uniform(0.2, 0.5))
            return True
        return False

    def init_browser(self):
        """初始化带有 Stealth 补丁的浏览器"""
        co = ChromiumOptions()
        if self.headless:
            # 适配 DrissionPage v4 新版 API / 原生 Chrome args
            co.set_argument('--headless=new')
            co.set_argument('--disable-gpu')
            
        co.set_argument('--ignore-certificate-errors')
        co.set_argument('--disable-notifications')
        if self.proxy:
            co.set_proxy(self.proxy)

        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-infobars')
        co.set_argument('--excludeSwitches=enable-automation')
        co.set_argument('--lang=zh-CN')
        
        ua = UserAgent(os='windows', browsers=['chrome'])
        co.set_user_agent(ua.random)

        self.page = ChromiumPage(co)
        
        try:
            self.page.run_js(STEALTH_JS)
            self.page.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=STEALTH_JS)
        except Exception as e:
            self.log(f"隐身保护注入异常: {e}")
            
        self.page.set.window.size(random.choice([1920, 1440, 1600]), random.choice([1080, 900]))
        self.page.set.timeouts(base=10)

    def extract_otp_code(self, html: str) -> str:
        """从原生邮件正文提取六位验证码"""
        patterns = [
            r'Verification code:?\s*(\d{6})',
            r'code is\s*(\d{6})',
            r'验证码[:：]?\s*(\d{6})',
            r'>\s*(\d{6})\s*<',
            r'\b(\d{6})\b',
        ]
        for p in patterns:
            m = re.search(p, html, re.IGNORECASE)
            if m and m.group(1) != "177010":
                return m.group(1)
        return ""

    def run(self, email: str, password: str) -> dict:
        self.log(f"[Adobe Browser] 开始初始化环境以注册 {email}...")
        self.init_browser()
        prof = self._gen_profile()

        try:
            # 1. 导航
            self.log("[Adobe] 1. 导航到目标地址...")
            self.page.get(self.SIGNUP_URL)
            self._wait_page_ready(20)
            self._delay(2, 3)

            # 2. 账号填写
            self.log("[Adobe] 2. 填写邮箱与密码...")
            email_field = None
            for sel in ['#EmailPage-EmailField', '#Signup-EmailField', 'input[type="email"]']:
                email_field = self.page.ele(sel, timeout=3)
                if email_field: break

            if not email_field:
                self._find_and_click(['使用电子邮件注册', '使用电子邮件继续注册'], timeout=10, label="邮箱入口")
                self._wait_page_ready()
                for sel in ['#EmailPage-EmailField', '#Signup-EmailField', 'input[type="email"]']:
                    email_field = self.page.ele(sel, timeout=3)
                    if email_field: break

            if not email_field:
                raise Exception("找不到邮箱输入框！")

            self._safe_type(email_field, email)
            self._delay(0.3, 0.8)

            pwd_field = None
            for sel in ['#PasswordPage-PasswordField', '#Signup-PasswordField', 'input[type="password"]']:
                pwd_field = self.page.ele(sel, timeout=3)
                if pwd_field: break
                
            if pwd_field:
                self._safe_type(pwd_field, password)

            if not self._find_and_click(['继续', 'Continue'], timeout=10, label="Step1 继续", tag_filter=['button', 'a', 'span']):
                self.page.actions.key_down('Enter').key_up('Enter')

            self._delay(3, 5)
            self._wait_page_ready()

            # 3. 个人资料填写
            self.log("[Adobe] 3. 填写个人资料信息...")
            if not pwd_field:
                pwd_field2 = self.page.ele('input[type="password"]', timeout=3)
                if pwd_field2: self._safe_type(pwd_field2, password)

            fn_field = self.page.ele('#Signup-FirstNameField', timeout=3) or self.page.ele('input[name="firstName"]', timeout=3)
            self._safe_type(fn_field, prof["fn"])
            ln_field = self.page.ele('#Signup-LastNameField', timeout=3) or self.page.ele('input[name="lastName"]', timeout=3)
            self._safe_type(ln_field, prof["ln"])

            month_field = self.page.ele('#Signup-DateOfBirthChooser-Month', timeout=3) or self.page.ele('select[name="month"]', timeout=3)
            if month_field:
                try:
                    month_field.select.by_value(str(prof["month"]))
                except:
                    month_field.click()
                    self._delay()
                    month_names = ["", "一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"]
                    self._find_and_click([month_names[prof["month"]]], timeout=5)
            
            self._delay(0.5)
            year_field = self.page.ele('#Signup-DateOfBirthChooser-Year', timeout=3) or self.page.ele('input[name="year"]', timeout=3)
            self._safe_type(year_field, str(prof["year"]))
            self._delay(0.5, 1)

            # 4. 提交
            self.log("[Adobe] 4. 提交注册...")
            url_before = self.page.url
            
            submit_btn = self.page.ele('tag:button@@text():创建帐户', timeout=2) or self.page.ele('tag:button@@text():Create account', timeout=2)
            if submit_btn and submit_btn.states.is_displayed:
                submit_btn.scroll.to_see()
                self._delay()
                submit_btn.click()
            else:
                self._find_and_click(['创建帐户', 'Create account'], timeout=5, tag_filter=['button'])

            # 检测跳转
            max_wait = 20
            start_w = time.time()
            page_changed = False
            while time.time() - start_w < max_wait:
                if self.page.url != url_before:
                    page_changed = True
                    break
                if self.page.ele('text:验证', timeout=1) or self.page.ele('text:Verify', timeout=1):
                    page_changed = True
                    break
                time.sleep(2)

            self._wait_page_ready()
            
            # 检测 Arkose
            if self.page.ele('xpath://iframe[contains(@src, "arkoselabs")]', timeout=3):
                raise Exception("Arkose 验证码拦截 (风控等级过高)")

            # 5. 接码
            self.log("[Adobe] 5. 等待验证码环节...")
            verify_texts = ['验证您的电子邮件', '验证码', 'Verify your email', 'verification']
            verify_page = False
            for step in range(5):
                for txt in verify_texts:
                    if self.page.ele(f'text:{txt}', timeout=2):
                        verify_page = True
                        break
                if verify_page: break
                time.sleep(2)

            if verify_page:
                self.log("📧 检测到验证码页面，呼叫 otp_callback 触发接码...")
                # 调用项目底层的全局 IMAP 接码机制 (包含轮询及阻塞等待)
                if self._otp_callback:
                    code_found = False
                    start_otp = time.time()
                    while time.time() - start_otp < 120 and not code_found:
                        content_dict = self._otp_callback()
                        if content_dict and isinstance(content_dict, dict):
                            body = content_dict.get('html_body') or content_dict.get('body') or ""
                            code = self.extract_otp_code(body)
                            if code:
                                self.log(f"🔑 拦截到验证码: {code}")
                                code_inputs = self.page.eles('input[maxlength="1"]', timeout=3)
                                if code_inputs and len(code_inputs) >= 6:
                                    for i, digit in enumerate(code[:6]):
                                        code_inputs[i].click()
                                        self._delay(0.05, 0.15)
                                        code_inputs[i].input(digit)
                                else:
                                    cf = self.page.ele('input[name="code"]', timeout=3) or self.page.ele('input[type="text"]', timeout=3)
                                    if cf: self._safe_type(cf, code)
                                
                                self._delay(1, 2)
                                self._find_and_click(['验证', '继续', 'Verify', 'Continue'], timeout=5, label="验证按钮", tag_filter=['button'])
                                self._delay(3, 5)
                                code_found = True
                                break
                        time.sleep(5)
                    
                    if not code_found:
                        self.log("⚠️ 验证码获取超时。账号可能仍算作创建。")

            # ============ 6. Firefly OAuth 授权 + 全域 Cookie 提取 ============
            cookie_str = ""
            try:
                # 6a. 导航到 Firefly 主页，完成完整的 OAuth consent 授权链路
                # 这一步是决定 Token 有效期（1h vs 24h）的关键！
                # 只有完成了 firefly.adobe.com 的 OAuth 授权流程，Cookie 中才会
                # 包含 firefly_api scope 的 consent 标记，Adobe IMS 才会签发 24h Token
                self.log("[Adobe] 6. 导航到 Firefly 主页完成 OAuth 授权...")
                try:
                    # 构造与浏览器插件完全一致的 Firefly 入口 URL（包含完整scope）
                    firefly_auth_url = (
                        "https://auth.services.adobe.com/zh_HANS/deeplink.html"
                        "?deeplink=ssofirst"
                        "&callback=https://firefly.adobe.com/"
                        "&client_id=clio-playground-web"
                        "&scope=AdobeID,firefly_api,openid,pps.read,pps.write,"
                        "additional_info.projectedProductContext,"
                        "additional_info.ownerOrg,uds_read,uds_write,ab.manage,"
                        "read_organizations,additional_info.roles,"
                        "account_cluster.read,creative_production"
                    )
                    self.page.get(firefly_auth_url)
                    self._wait_page_ready(20)
                    self._delay(3, 5)

                    # 等待 OAuth consent 重定向并处理可能的授权弹窗
                    max_consent_wait = 30
                    consent_start = time.time()
                    while time.time() - consent_start < max_consent_wait:
                        current_url = self.page.url or ""

                        # 如果已经成功跳转到 firefly.adobe.com，说明授权完成
                        if "firefly.adobe.com" in current_url and "auth.services" not in current_url:
                            self.log("✅ Firefly OAuth 授权跳转完成!")
                            break

                        # 检查是否出现了 consent（授权同意）页面
                        consent_btn = None
                        for sel in ['button:contains("允许")', 'button:contains("Allow")',
                                     'button:contains("同意")', 'button:contains("Agree")',
                                     'button:contains("Accept")', 'button:contains("接受")']:
                            try:
                                consent_btn = self.page.ele(sel, timeout=1)
                                if consent_btn and consent_btn.states.is_displayed:
                                    break
                                consent_btn = None
                            except Exception:
                                consent_btn = None

                        if consent_btn:
                            self.log("🔑 检测到 OAuth 授权同意页面，正在点击同意...")
                            try:
                                consent_btn.click()
                                self._delay(2, 3)
                            except Exception:
                                pass
                                
                        # 有可能出现 "Continue / 继续" 提示页
                        continue_btn = None
                        for sel in ['button:contains("Continue")', 'button:contains("继续")', 'a:contains("Continue")', 'a:contains("继续")']:
                            try:
                                continue_btn = self.page.ele(sel, timeout=1)
                                if continue_btn and continue_btn.states.is_displayed:
                                    break
                                continue_btn = None
                            except Exception:
                                continue_btn = None
                                
                        if continue_btn:
                            self.log("🔑 检测到继续跳转页面，正在点击继续...")
                            try:
                                continue_btn.click()
                                self._delay(2, 3)
                            except Exception:
                                pass

                        # 检测是否需要接受 Firefly Terms of Service
                        tos_texts = ['服务条款', 'Terms of Service', 'Terms of Use',
                                     'I agree', '我同意', 'Get started', '开始使用']
                        for txt in tos_texts:
                            try:
                                tos_ele = self.page.ele(f'text:{txt}', timeout=1)
                                if tos_ele and tos_ele.states.is_displayed:
                                    tag = tos_ele.tag.lower()
                                    if tag in ('button', 'a', 'span', 'label', 'input'):
                                        self.log(f"📋 检测到服务条款确认: '{txt}'，正在点击...")
                                        tos_ele.click()
                                        self._delay(2, 3)
                                        break
                            except Exception:
                                continue

                        time.sleep(2)

                    # 确保最终停留在 firefly.adobe.com 上
                    final_url = self.page.url or ""
                    # 避免 final_url 包含 callback=firefly.adobe.com 却没真正跳转过去的情况
                    if not final_url.startswith("https://firefly.adobe.com"):
                        self.log("[Adobe] 6a-retry. 未正确跳转，强制导航到 Firefly 首页...")
                        self.page.get("https://firefly.adobe.com/")
                        self._wait_page_ready(15)
                        self._delay(3, 5)

                    self.log(f"[Adobe] 6a. 当前页面: {self.page.url}")

                except Exception as nav_err:
                    self.log(f"⚠️ Firefly OAuth 授权流程异常 (尝试直接导航): {nav_err}")
                    try:
                        self.page.get("https://firefly.adobe.com/")
                        self._wait_page_ready(15)
                        self._delay(3, 5)
                    except Exception:
                        pass

                # 6b. 使用 CDP Network.getAllCookies 提取浏览器内全部域名的 Cookie
                # 关键：page.cookies() 可能不返回 HttpOnly Cookie (如 ims_sid)
                # 而 CDP Network.getAllCookies 等同于 chrome.cookies.getAll()，能获取全部 Cookie
                self.log("[Adobe] 6b. 提取全域 Cookie...")
                all_cookies = []
                try:
                    # 优先使用 CDP 协议获取完整 Cookie（包含 HttpOnly）
                    cdp_result = self.page.run_cdp('Network.getAllCookies')
                    all_cookies = cdp_result.get('cookies', [])
                    self.log(f"[Adobe] CDP getAllCookies 返回 {len(all_cookies)} 条")
                except Exception as cdp_err:
                    self.log(f"⚠️ CDP getAllCookies 失败，回退 page.cookies: {cdp_err}")
                    try:
                        all_cookies = self.page.cookies(all_domains=True)
                    except TypeError:
                        all_cookies = self.page.cookies()
                
                # 诊断日志: 检查关键 Cookie 是否在原始列表中
                critical_keys = {'ims_sid', 'aux_sid', 'AWSELB', 'AWSELBCORS'}
                found_critical = set()
                for c in all_cookies:
                    cname = c.get('name', '') if isinstance(c, dict) else getattr(c, 'name', '')
                    if cname in critical_keys:
                        cdomain = c.get('domain', '') if isinstance(c, dict) else getattr(c, 'domain', '')
                        found_critical.add(cname)
                        self.log(f"  🔑 [关键Cookie] {cname} @ {cdomain}")
                if not found_critical:
                    self.log("  ⚠️ 未在浏览器中发现 ims_sid / aux_sid 等关键 Cookie")

                # 6c. 仅保留 Adobe 相关域名下的 Cookie (与浏览器插件提取范围一致)
                adobe_domains = ('adobe.com', 'firefly.adobe.com', 'account.adobe.com',
                                 'auth.services.adobe.com', 'adobelogin.com')
                filtered = []
                seen_keys = set()

                for c in all_cookies:
                    if isinstance(c, dict):
                        domain = str(c.get('domain', '')).lower().strip()
                        name = str(c.get('name', '')).strip()
                        value = str(c.get('value', '')).strip()
                    else:
                        # 兼容某些版本返回 Cookie 对象
                        domain = str(getattr(c, 'domain', '')).lower().strip()
                        name = str(getattr(c, 'name', '')).strip()
                        value = str(getattr(c, 'value', '')).strip()

                    if not name:
                        continue

                    # 检查域名是否属于 Adobe 体系 (去除前导点的影响)
                    clean_domain = domain.lstrip('.')
                    is_adobe = any(clean_domain == d or clean_domain.endswith('.' + d) for d in adobe_domains)
                    if not is_adobe:
                        continue

                    # 去重 (与浏览器插件的 seen Set 逻辑一致)
                    dedup_key = f"{domain}|{name}"
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    filtered.append(f"{name}={value}")

                cookie_str = "; ".join(filtered)
                self.log(f"🍪 成功提取全域 Cookie (共 {len(filtered)} 条, 长度: {len(cookie_str)})")

                # 6d. 自动推送至 adobe2api (保留原有逻辑)
                if cookie_str:
                    import requests
                    import os
                    try:
                        self.log("🚀 正在将新凭证 Cookie 推送至内置 adobe2api (6001)...")
                        # 支持用户通过环境变量自定义地址，例如在 docker-compose 中配置 ADOBE2API_URL
                        custom_url = os.environ.get("ADOBE2API_URL")
                        
                        if custom_url:
                            resp = requests.post(
                                custom_url, 
                                json={"cookie": cookie_str, "name": email},
                                timeout=4
                            )
                        else:
                            # 兼容 Docker 环境内与 Host 主机间的通讯
                            try:
                                resp = requests.post(
                                    "http://adobe2api:6001/api/v1/refresh-profiles/import-cookie", 
                                    json={"cookie": cookie_str, "name": email},
                                    timeout=4
                                )
                            except requests.exceptions.ConnectionError:
                                resp = requests.post(
                                    "http://172.17.0.1:6001/api/v1/refresh-profiles/import-cookie", 
                                    json={"cookie": cookie_str, "name": email},
                                    timeout=4
                                )

                        if resp.status_code == 200:
                            self.log("✅ 成功对接并导入至 adobe2api!")
                        else:
                            self.log(f"⚠️ 导入 adobe2api 返回异常 Http {resp.status_code}")
                    except Exception as he:
                        self.log(f"⚠️ 尝试自动推送 adobe2api 失败 (请检查网络层或环境变量配置): {he}")
            except Exception as e:
                self.log(f"⚠️ 提取 Cookie 发生异常: {e}")

            return {
                "email": email,
                "password": password,
                "token": cookie_str,  # 将完整 Cookie 填充至 Token 字段展示
                "extra": {"created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            }

        except Exception as e:
            self.log(f"注册崩溃异常: {e}")
            raise e
        finally:
            if self.page:
                self.page.quit()

