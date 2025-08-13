from flask import Flask, request, jsonify
import os
import traceback

app = Flask(__name__)

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

print(f"=== 啟動時檢查 ===")
print(f"Access Token 長度: {len(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else 0}")
print(f"Channel Secret 長度: {len(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else 0}")
print(f"Access Token 前20字: {LINE_CHANNEL_ACCESS_TOKEN[:20] if LINE_CHANNEL_ACCESS_TOKEN else 'None'}")

# 基本健康檢查
@app.route("/", methods=['GET'])
def health_check():
    return jsonify({
        "status": "running",
        "message": "🤖 極簡除錯版本",
        "debug_info": {
            "access_token_length": len(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else 0,
            "secret_length": len(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else 0,
            "access_token_prefix": LINE_CHANNEL_ACCESS_TOKEN[:20] if LINE_CHANNEL_ACCESS_TOKEN else None,
            "environment_vars": {
                "LINE_CHANNEL_ACCESS_TOKEN": bool(LINE_CHANNEL_ACCESS_TOKEN),
                "LINE_CHANNEL_SECRET": bool(LINE_CHANNEL_SECRET),
                "SPREADSHEET_ID": bool(os.environ.get('SPREADSHEET_ID')),
                "GOOGLE_CREDENTIALS": bool(os.environ.get('GOOGLE_CREDENTIALS'))
            }
        }
    })

# 極簡 Webhook - 直接返回 200
@app.route("/api/webhook", methods=['POST'])
def webhook():
    try:
        print("=" * 50)
        print("📨 收到 Webhook 請求")
        
        # 記錄所有請求資訊
        print(f"Method: {request.method}")
        print(f"Headers: {dict(request.headers)}")
        
        # 取得請求內容
        body = request.get_data(as_text=True)
        print(f"Body length: {len(body)}")
        print(f"Body preview: {body[:200] if body else 'Empty'}")
        
        # 檢查重要的 headers
        signature = request.headers.get('X-Line-Signature', '')
        user_agent = request.headers.get('User-Agent', '')
        content_type = request.headers.get('Content-Type', '')
        
        print(f"Signature: {signature}")
        print(f"User-Agent: {user_agent}")
        print(f"Content-Type: {content_type}")
        
        # 檢查環境變數
        print(f"Access Token 存在: {bool(LINE_CHANNEL_ACCESS_TOKEN)}")
        print(f"Channel Secret 存在: {bool(LINE_CHANNEL_SECRET)}")
        
        # 嘗試解析 JSON
        if body:
            try:
                import json
                data = json.loads(body)
                print(f"JSON 解析成功: {data}")
            except Exception as e:
                print(f"JSON 解析失敗: {e}")
        
        print("✅ 直接返回 200 OK")
        print("=" * 50)
        
        # 直接返回成功，不做任何處理
        return jsonify({
            "status": "OK", 
            "message": "Webhook received successfully",
            "debug": "極簡版本 - 直接返回200"
        }), 200
        
    except Exception as e:
        print(f"❌ Webhook 發生錯誤: {e}")
        print(f"錯誤詳情: {traceback.format_exc()}")
        
        # 即使發生錯誤也返回 200
        return jsonify({
            "status": "ERROR", 
            "error": str(e),
            "message": "即使錯誤也返回200"
        }), 200

# 測試用的簡單 POST endpoint
@app.route("/test", methods=['POST'])
def test_post():
    return jsonify({"status": "POST test OK"}), 200

if __name__ == "__main__":
    app.run(debug=True)
