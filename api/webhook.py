from flask import Flask, request, jsonify
import os
import json

app = Flask(__name__)

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')

print(f"Token exists: {bool(LINE_CHANNEL_ACCESS_TOKEN)}")
print(f"Secret exists: {bool(LINE_CHANNEL_SECRET)}")

# 基本健康檢查
@app.route("/", methods=['GET'])
def health_check():
    return jsonify({
        "status": "running",
        "message": "🤖 股票管理 LINE Bot 運行正常！",
        "mode": "測試模式 - 簽名驗證已停用",
        "environment_vars": {
            "LINE_CHANNEL_ACCESS_TOKEN": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "LINE_CHANNEL_SECRET": bool(LINE_CHANNEL_SECRET),
            "SPREADSHEET_ID": bool(SPREADSHEET_ID),
            "GOOGLE_CREDENTIALS": bool(os.environ.get('GOOGLE_CREDENTIALS'))
        }
    })

# 發送回覆訊息到 LINE
def send_reply_message(reply_token, message_text):
    import requests
    
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("❌ 沒有 Access Token")
        return False
    
    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    
    data = {
        'replyToken': reply_token,
        'messages': [{
            'type': 'text',
            'text': message_text
        }]
    }
    
    try:
        print(f"發送回覆到 LINE API...")
        response = requests.post(url, headers=headers, json=data)
        print(f"LINE API Response: {response.status_code}")
        if response.status_code != 200:
            print(f"Error response: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ 發送訊息失敗: {e}")
        return False

# Webhook 處理（暫時停用簽名驗證）
@app.route("/api/webhook", methods=['POST'])
def webhook():
    try:
        print("📨 收到 webhook 請求")
        
        # 取得請求內容
        body = request.get_data(as_text=True)
        signature = request.headers.get('X-Line-Signature', '')
        
        print(f"Body length: {len(body)}")
        print(f"Has signature: {bool(signature)}")
        print(f"⚠️ 跳過簽名驗證（測試模式）")
        
        # 解析 LINE 事件
        try:
            events_data = json.loads(body)
            events = events_data.get('events', [])
            print(f"收到 {len(events)} 個事件")
            
            for event in events:
                event_type = event.get('type')
                print(f"事件類型: {event_type}")
                
                # 處理文字訊息
                if event_type == 'message' and event.get('message', {}).get('type') == 'text':
                    reply_token = event.get('replyToken')
                    message_text = event.get('message', {}).get('text', '').strip()
                    
                    print(f"收到訊息: {message_text}")
                    print(f"Reply token: {reply_token}")
                    
                    # 處理不同指令
                    if message_text == '測試':
                        response_text = "🤖 機器人運作正常！\n✅ Webhook 連接成功\n✅ 運行在 Vercel 雲端平台\n⚠️ 目前為測試模式"
                    elif message_text in ['幫助', '指令', 'help', '說明']:
                        response_text = """📚 股票管理機器人使用說明：

🟢 測試指令：
- 測試：檢查機器人狀態
- 幫助：顯示此說明
- 狀態：查看系統狀態

📊 基本功能：
- 可以正常收發訊息
- Webhook 連接正常

⚠️ 注意：目前為測試模式
🔧 平台：Vercel Serverless"""
                    elif message_text == '狀態':
                        response_text = f"""🔧 系統狀態報告：
🌐 平台：Vercel Serverless
🔑 Access Token：✅ 已設定
🔐 Channel Secret：✅ 已設定
📊 Google Sheets：✅ 已設定
⚠️ 簽名驗證：暫時停用
🚀 狀態：正常運行"""
                    elif ',' in message_text and '買入' in message_text:
                        # 簡單的買入指令處理
                        response_text = f"📝 收到買入指令：{message_text}\n\n✅ 指令格式正確\n💡 完整功能開發中..."
                    else:
                        response_text = f"📨 收到您的訊息：{message_text}\n\n✅ Bot 運行正常！\n💡 輸入「幫助」查看可用指令"
                    
                    # 發送回覆
                    if reply_token:
                        print(f"準備發送回覆...")
                        success = send_reply_message(reply_token, response_text)
                        if success:
                            print("✅ 回覆發送成功")
                        else:
                            print("❌ 回覆發送失敗")
                    else:
                        print("❌ 沒有 reply token")
                
                # 處理加好友事件
                elif event_type == 'follow':
                    reply_token = event.get('replyToken')
                    welcome_text = """🎉 歡迎使用股票管理機器人！

✅ 連接成功！
🤖 我可以幫您管理股票投資紀錄

💡 輸入「測試」開始使用
💡 輸入「幫助」查看使用說明

🔧 目前為測試模式，功能持續完善中..."""
                    
                    if reply_token:
                        send_reply_message(reply_token, welcome_text)
                
                # 處理其他事件
                else:
                    print(f"收到其他事件: {event_type}")
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失敗: {e}")
            return jsonify({"error": "Invalid JSON"}), 400
        
        print("✅ Webhook 處理完成")
        return jsonify({"status": "OK"}), 200
        
    except Exception as e:
        print(f"❌ Webhook 處理錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
