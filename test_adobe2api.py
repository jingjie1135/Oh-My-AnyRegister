import sys
from curl_cffi import requests

api_url = "http://127.0.0.1:6001"
username = "admin"
password = "admin"

print(f"[*] 准备连接到 Adobe2API 服务器: {api_url}")
print(f"[*] 使用管理员鉴权: {username} / {password}\n")

try:
    with requests.Session() as s:
        # Step 1: Login to get session
        login_url = f"{api_url}/api/v1/auth/login"
        print(f"[1] 请求登录鉴权: POST {login_url}")
        
        login_resp = s.post(
            login_url,
            json={"username": username, "password": password},
            timeout=10,
            impersonate="chrome110"
        )
        print(f"    <- 状态码: {login_resp.status_code}")
        print(f"    <- 返回值: {login_resp.text}")
        
        if login_resp.status_code != 200 or login_resp.json().get("status") != "ok":
            print("\n[!] 登录失败！配置不正确或服务器拒绝连接。")
            sys.exit(1)
            
        print("\n[V] 登录成功！已成功截获管理后台鉴权用 Session Cookie。")
        print(f"    => 获取到的 Cookies: {s.cookies.get_dict()}")
        
        # Step 2: Test importing a cookie
        import_cookie_url = f"{api_url}/api/v1/refresh-profiles/import-cookie"
        print(f"\n[2] 测试凭据下发: POST {import_cookie_url}")
        
        dummy_account = {
            "cookie": "dummy_cookie_test=1;",
            "name": "test_account@example.com"
        }
        print(f"    -> 提交数据: {dummy_account}")
        
        headers = {"Content-Type": "application/json"}
        import_resp = s.post(
            import_cookie_url,
            headers=headers,
            json=dummy_account,
            timeout=15,
            impersonate="chrome110"
        )
        print(f"    <- 状态码: {import_resp.status_code}")
        print(f"    <- 返回值: {import_resp.text}")
        
        if import_resp.status_code in (200, 201):
            print("\n[V] 导入凭据操作成功！通信链路双向检测通过。")
        elif import_resp.status_code == 400:
            print("\n[!] 导入失败: 服务拒绝了模拟凭据 (格式或参数错误)。通信其实是畅通的！")
        else:
            print("\n[!] 导入失败！")
except Exception as e:
    print(f"\n[!] 脚本执行期间发生致命异常: {e}")
