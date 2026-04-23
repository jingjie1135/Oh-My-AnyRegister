import sys
import time
import requests

def check_tempmail(token):
    print(f"正在查询收件箱...\nToken: {token}")
    try:
        resp = requests.get(f"https://api.tempmail.lol/v2/inbox?token={token}")
        resp.raise_for_status()
        emails = resp.json().get("emails", [])
        
        if not emails:
            print("📭 目前收件箱是空的，还没有收到新邮件。")
            return
            
        print(f"📬 收到 {len(emails)} 封邮件:\n" + "="*40)
        for i, e in enumerate(emails):
            sender = e.get("from", "未知发件人")
            subject = e.get("subject", "无主题")
            body = e.get("body", "") or e.get("html", "")
            print(f"【邮件 {i+1}】")
            print(f"发件人: {sender}")
            print(f"主题: {subject}")
            
            # 尝试提取验证码
            import re
            m = re.search(r'\b(\d{6})\b', body)
            if m:
                print(f"🔑 识别到 6 位验证码: >>> {m.group(1)} <<<")
            else:
                print("内容预览:", body[:200].replace('\n', ' '))
            print("-" * 40)
            
    except Exception as ex:
        print(f"❌ 查询失败: {ex}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        token = sys.argv[1]
    else:
        token = input("请输入 TempMail 的 Token (ID): ").strip()
    
    if token:
        check_tempmail(token)
    else:
        print("未输入 Token")
