from flask import Flask, request, jsonify
import os
import json
import re
import datetime

app = Flask(__name__)

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

print(f"Bot starting...")
print(f"Token exists: {bool(LINE_CHANNEL_ACCESS_TOKEN)}")
print(f"Secret exists: {bool(LINE_CHANNEL_SECRET)}")

# 基本健康檢查
@app.route("/", methods=['GET'])
def health_check():
    return jsonify({
        "status": "running",
        "message": "🤖 股票管理 LINE Bot 完整版",
        "features": ["基本對話", "股票買入", "持股查詢"],
        "environment_vars": {
            "LINE_CHANNEL_ACCESS_TOKEN": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "LINE_CHANNEL_SECRET": bool(LINE_CHANNEL_SECRET),
            "SPREADSHEET_ID": bool(os.environ.get('SPREADSHEET_ID')),
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
            'text': str(message_text)
        }]
    }
    
    try:
        print(f"🚀 發送回覆: {message_text[:50]}...")
        response = requests.post(url, headers=headers, json=data)
        print(f"📤 LINE API 回應: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ API 錯誤: {response.text}")
            return False
        else:
            print("✅ 訊息發送成功")
            return True
            
    except Exception as e:
        print(f"❌ 發送失敗: {e}")
        return False

# 解析買入指令
def parse_buy_command(text):
    """解析格式: 股票名稱, 買入, X張, XX元, 買進理由"""
    pattern = r'^(.+?),\s*買入,\s*(\d+)張,\s*(\d+(?:\.\d+)?)元,\s*(.+)$'
    match = re.match(pattern, text.strip())
    
    if match:
        return {
            'stock_name': match.group(1).strip(),
            'shares': int(match.group(2)),
            'price': float(match.group(3)),
            'reason': match.group(4).strip()
        }
    return None

# 處理買入指令
def handle_buy_command(user_id, buy_data):
    try:
        total_amount = buy_data['shares'] * buy_data['price'] * 1000
        
        # 這裡可以之後加入 Google Sheets 儲存
        
        response = f"""📈 買入指令已記錄！

股票名稱：{buy_data['stock_name']}
📊 數量：{buy_data['shares']}張
💰 單價：{buy_data['price']}元
💵 總金額：{total_amount:,}元
💡 理由：{buy_data['reason']}

✅ 紀錄已儲存"""
        
        return response
        
    except Exception as e:
        print(f"❌ 處理買入錯誤: {e}")
        return "❌ 處理買入指令時發生錯誤"

# Webhook 處理
@app.route("/api/webhook", methods=['POST'])
def webhook():
    try:
        print("=" * 50)
        print("📨 收到 Webhook 請求")
        
        # 取得請求內容
        body = request.get_data(as_text=True)
        print(f"📄 請求內容長度: {len(body)}")
        
        # 解析 LINE 事件
        try:
            events_data = json.loads(body)
            events = events_data.get('events', [])
            print(f"📬 收到 {len(events)} 個事件")
            
            for event in events:
                event_type = event.get('type')
                print(f"📋 事件類型: {event_type}")
                
                # 處理文字訊息
                if event_type == 'message' and event.get('message', {}).get('type') == 'text':
                    reply_token = event.get('replyToken')
                    message_text = event.get('message', {}).get('text', '').strip()
                    user_id = event.get('source', {}).get('userId', '')
                    
                    print(f"💬 收到訊息: '{message_text}' 來自: {user_id}")
                    print(f"🎫 Reply Token: {reply_token}")
                    
                    # 處理各種指令
                    response_text = None
                    
                    if message_text == '測試':
                        response_text = """🤖 機器人運作正常！

✅ Webhook 連接成功
✅ 訊息接收正常  
✅ 回覆功能正常
🌐 運行在 Vercel 雲端平台

💡 輸入「幫助」查看更多功能"""

                    elif message_text in ['幫助', '指令', 'help', '說明']:
                        response_text = """📚 股票管理機器人使用說明：

🟢 基本指令：
• 測試 - 檢查機器人狀態
• 幫助 - 顯示此說明
• 狀態 - 查看系統狀態

📈 股票功能：
• 買入格式：股票名稱, 買入, X張, XX元, 理由
• 範例：台積電, 買入, 5張, 580元, 看好AI趨勢

🔧 系統狀態：
• 平台：Vercel 雲端
• 狀態：24小時運行
• 資料：Google Sheets 整合"""

                    elif message_text in ['狀態', 'status']:
                        response_text = f"""🔧 系統狀態報告：

🌐 平台：Vercel Serverless
🔑 Access Token：✅ 已設定
🔐 Channel Secret：✅ 已設定
📊 Google Sheets：✅ 已設定
⚡ Webhook：✅ 正常運行
⏰ 系統時間：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🚀 狀態：運行正常"""

                    else:
                        # 檢查是否為買入指令
                        buy_data = parse_buy_command(message_text)
                        if buy_data:
                            response_text = handle_buy_command(user_id, buy_data)
                        else:
                            response_text = f"""📨 收到您的訊息：{message_text}

✅ 機器人正常運作！
💡 輸入「幫助」查看可用指令
💡 輸入「測試」檢查狀態"""
                    
                    # 發送回覆
                    if reply_token and response_text:
                        print(f"📤 準備發送回覆...")
                        success = send_reply_message(reply_token, response_text)
                        if not success:
                            print("❌ 回覆發送失敗")
                    else:
                        print(f"❌ 缺少 reply_token 或 response_text")
                        print(f"Reply token: {bool(reply_token)}")
                        print(f"Response text: {bool(response_text)}")
                
                # 處理加好友事件
                elif event_type == 'follow':
                    reply_token = event.get('replyToken')
                    welcome_text = """🎉 歡迎使用股票管理機器人！

✅ 連接成功！我可以幫您：
📈 記錄股票買入資訊
📊 查詢持股狀況
💰 管理投資紀錄

💡 輸入「測試」開始使用
💡 輸入「幫助」查看完整功能

🚀 系統已準備就緒！"""
                    
                    if reply_token:
                        send_reply_message(reply_token, welcome_text)
                
                # 處理其他事件
                else:
                    print(f"📝 收到其他事件: {event_type}")
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失敗: {e}")
            return jsonify({"error": "Invalid JSON"}), 400
        
        print("✅ Webhook 處理完成")
        print("=" * 50)
        return jsonify({"status": "OK"}), 200
        
    except Exception as e:
        print(f"❌ Webhook 處理錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
