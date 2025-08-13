from flask import Flask, request, jsonify
import os
import json
import hashlib
import hmac
import base64

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
        "environment_vars": {
            "LINE_CHANNEL_ACCESS_TOKEN": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "LINE_CHANNEL_SECRET": bool(LINE_CHANNEL_SECRET),
            "SPREADSHEET_ID": bool(SPREADSHEET_ID),
            "GOOGLE_CREDENTIALS": bool(os.environ.get('GOOGLE_CREDENTIALS'))
        }
    })

# 驗證 LINE 簽名
def validate_signature(body, signature):
    if not LINE_CHANNEL_SECRET:
        print("❌ 沒有 Channel Secret")
        return False
    
    hash = hmac.new(
        LINE_CHANNEL_SECRET.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).digest()
    
    expected_signature = base64.b64encode(hash).decode('utf-8')
    
    print(f"Expected: {expected_signature}")
    print(f"Received: {signature}")
    
    return expected_signature == signature

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
        response = requests.post(url, headers=headers, json=data)
        print(f"LINE API Response: {response.status_code} - {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ 發送訊息失敗: {e}")
        return False

# Webhook 處理
@app.route("/api/webhook", methods=['POST'])
def webhook():
    try:
        # 取得請求內容
        body = request.get_data(as_text=True)
        signature = request.headers.get('X-Line-Signature', '')
        
        print(f"📨 收到 webhook 請求")
        print(f"Body length: {len(body)}")
        print(f"Signature: {signature}")
        
        # 驗證簽名
        if not validate_signature(body, signature):
            print("❌ 簽名驗證失敗")
            return jsonify({"error": "Invalid signature"}), 401
        
        print("✅ 簽名驗證成功")
        
        # 解析 LINE 事件
        try:
            events_data = json.loads(body)
            events = events_data.get('events', [])
            print(f"收到 {len(events)} 個事件")
            
            for event in events:
                print(f"事件類型: {event.get('type')}")
                
                # 處理文字訊息
                if event.get('type') == 'message' and event.get('message', {}).get('type') == 'text':
                    reply_token = event.get('replyToken')
                    message_text = event.get('message', {}).get('text', '').strip()
                    
                    print(f"收到訊息: {message_text}")
                    
                    # 處理不同指令
                    if message_text == '測試':
                        response_text = "🤖 機器人運作正常！運行在 Vercel 雲端平台\n輸入「幫助」查看使用說明"
                    elif message_text in ['幫助', '指令', 'help', '說明']:
                        response_text = """📚 股票管理機器人使用說明：

🟢 買入股票：
格式：股票名稱, 買入, X張, XX元, 買進理由
範例：台積電, 買入, 5張, 580元, 看好AI趨勢

📊 查詢功能：
- 持股：查看您的持股狀況  
- 幫助：顯示此說明
- 測試：檢查機器人狀態

⚠️ 注意事項：
- 所有交易都會記錄在案
- 買進理由有助於投資紀律

🔧 系統狀態：運行在 Vercel 雲端平台"""
                    elif message_text == '狀態':
                        response_text = f"""🔧 系統狀態報告：
🌐 平台：Vercel Serverless
⏰ 時間：目前運行正常
🚀 狀態：正常運行
💾 資料儲存：準備中"""
                    else:
                        response_text = f"📨 收到您的訊息：{message_text}\n\n❓ 請輸入「幫助」查看使用說明"
                    
                    # 發送回覆
                    if reply_token:
                        success = send_reply_message(reply_token, response_text)
                        if success:
                            print("✅ 回覆發送成功")
                        else:
                            print("❌ 回覆發送失敗")
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失敗: {e}")
            return jsonify({"error": "Invalid JSON"}), 400
        
        return jsonify({"status": "OK"}), 200
        
    except Exception as e:
        print(f"❌ Webhook 處理錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
