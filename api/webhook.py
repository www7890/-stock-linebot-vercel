from flask import Flask, request, jsonify
import os

app = Flask(__name__)

# 基本健康檢查
@app.route("/", methods=['GET'])
def health_check():
    return jsonify({
        "status": "running",
        "message": "🤖 股票管理 LINE Bot 運行正常！",
        "environment_vars": {
            "LINE_CHANNEL_ACCESS_TOKEN": bool(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')),
            "LINE_CHANNEL_SECRET": bool(os.environ.get('LINE_CHANNEL_SECRET')),
            "SPREADSHEET_ID": bool(os.environ.get('SPREADSHEET_ID')),
            "GOOGLE_CREDENTIALS": bool(os.environ.get('GOOGLE_CREDENTIALS'))
        }
    })

# 簡化的 webhook
@app.route("/api/webhook", methods=['POST'])
def webhook():
    try:
        return jsonify({"status": "webhook received"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
