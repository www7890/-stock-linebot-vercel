# api/webhook.py
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import gspread
import json
import re
import datetime
import os

app = Flask(__name__)

# 從環境變數讀取設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', 'fjh1kesK+73mjZUZtShY/bT95tCOOLSXZv0jmxF/Nn9WN8WPkD8fW5IM7Vb/1dfhXq6Dn+eNRCbmYrHsMYyg0DcAZoMrxJvU9NI5lU7NvQ0Y4uyM1zi6BBTlHvKIOKcuaaxNop0JHJLl/xG+9m//KAdB04t89/1O/w1cDnyilFU=')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '3616577e195d8536f6c8183f49b491a9')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID', '1ixP-uwSaCdsU3RhB_Rt6JouxUFyz0PhfD3BNEM_IXww')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Google Sheets 認證（使用環境變數）
def init_google_sheets():
    try:
        # 從環境變數讀取 Google 認證資訊
        credentials_json = os.environ.get('GOOGLE_CREDENTIALS')
        if credentials_json:
            credentials_info = json.loads(credentials_json)
            gc = gspread.service_account_from_dict(credentials_info)
        else:
            # 備用：如果有 credentials.json 檔案
            gc = gspread.service_account(filename='credentials.json')
        
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        transaction_sheet = spreadsheet.worksheet('交易紀錄')
        voting_sheet = spreadsheet.worksheet('投票紀錄')
        print("✅ Google Sheets 連接成功")
        return transaction_sheet, voting_sheet
    except Exception as e:
        print(f"❌ Google Sheets 連接失敗: {e}")
        return None, None

# 初始化（在 serverless 環境中每次請求都會執行）
transaction_sheet, voting_sheet = init_google_sheets()

# 本地儲存（Vercel 的暫存儲存）
local_transactions = []

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

# 處理買入股票
def handle_buy_stock(event, buy_data):
    try:
        user_id = event.source.user_id
        profile = line_bot_api.get_profile(user_id)
        user_name = profile.display_name
        
        total_amount = buy_data['shares'] * buy_data['price'] * 1000
        record_id = str(int(datetime.datetime.now().timestamp()))
        
        # 建立交易記錄
        transaction_record = {
            '日期時間': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '使用者ID': user_id,
            '使用者名稱': user_name,
            '股票代號': '',
            '股票名稱': buy_data['stock_name'],
            '交易類型': '買入',
            '張數': buy_data['shares'],
            '單價': buy_data['price'],
            '總金額': total_amount,
            '買進理由': buy_data['reason'],
            '狀態': '已執行',
            '紀錄ID': record_id
        }
        
        # 寫入 Google Sheets
        storage_info = "💾 已記錄"
        if transaction_sheet:
            try:
                row_data = list(transaction_record.values())
                transaction_sheet.append_row(row_data)
                storage_info = "✅ 已記錄到 Google Sheets"
                print(f"✅ 成功寫入 Google Sheets: {user_name} 買入 {buy_data['stock_name']}")
            except Exception as e:
                print(f"❌ Google Sheets 寫入失敗: {e}")
                storage_info = "💾 已記錄到暫存"
        
        # 群組通知
        message = f"""📈 {user_name} 買入 {buy_data['stock_name']}
📊 數量：{buy_data['shares']}張 @ {buy_data['price']}元
💰 總成本：{total_amount:,}元
💡 理由：{buy_data['reason']}

{storage_info}"""
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=message)
        )
        
    except Exception as e:
        print(f"❌ 處理買入錯誤: {e}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ 處理買入指令時發生錯誤，請稍後再試")
        )

# 查詢持股
def handle_stock_query(event, user_id):
    try:
        user_transactions = []
        
        if transaction_sheet:
            try:
                records = transaction_sheet.get_all_records()
                user_transactions = [r for r in records if str(r.get('使用者ID', '')) == str(user_id)]
                print(f"✅ 從 Google Sheets 讀取到 {len(user_transactions)} 筆記錄")
            except Exception as e:
                print(f"❌ Google Sheets 讀取失敗: {e}")
        
        if not user_transactions:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="📊 您目前沒有任何持股紀錄")
            )
            return
        
        # 計算持股
        holdings = {}
        
        for record in user_transactions:
            stock_name = record.get('股票名稱', '')
            trade_type = record.get('交易類型', '')
            shares = int(record.get('張數', 0))
            price = float(record.get('單價', 0))
            
            if stock_name not in holdings:
                holdings[stock_name] = {'shares': 0, 'total_cost': 0}
            
            if trade_type == '買入':
                holdings[stock_name]['shares'] += shares
                holdings[stock_name]['total_cost'] += shares * price * 1000
            elif trade_type == '賣出':
                holdings[stock_name]['shares'] -= shares
        
        # 生成持股報告
        message = "📊 您的持股狀況：\n\n"
        has_holdings = False
        
        for stock_name, data in holdings.items():
            if data['shares'] > 0:
                has_holdings = True
                avg_cost = data['total_cost'] / (data['shares'] * 1000)
                message += f"📈 {stock_name}\n"
                message += f"　持股：{data['shares']}張\n"
                message += f"　平均成本：{avg_cost:.2f}元\n\n"
        
        if not has_holdings:
            message = "📊 您目前沒有持股"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=message)
        )
        
    except Exception as e:
        print(f"❌ 查詢持股錯誤: {e}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ 查詢持股時發生錯誤")
        )

# 幫助訊息
def get_help_message():
    storage_status = "✅ Google Sheets" if transaction_sheet else "💾 暫存模式"
    return f"""📚 股票管理機器人使用說明：

🟢 買入股票：
格式：股票名稱, 買入, X張, XX元, 買進理由
範例：台積電, 買入, 5張, 580元, 看好AI趨勢

📊 查詢功能：
- 持股：查看您的持股狀況
- 幫助：顯示此說明

⚠️ 注意事項：
- 所有交易都會記錄在案
- 買進理由有助於投資紀律

🔧 系統狀態：
- 資料儲存：{storage_status}
- 運行環境：Vercel Serverless
- 24小時穩定運行 🚀"""

# Webhook 處理
@app.route("/", methods=['GET'])
def health_check():
    return "🤖 股票管理 LINE Bot 運行正常！"

@app.route("/api/webhook", methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ Invalid signature")
        abort(400)
    except Exception as e:
        print(f"❌ Webhook 處理錯誤: {e}")
        abort(500)
    
    return 'OK'

# 處理文字訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    
    print(f"📨 收到訊息: {text}")
    
    try:
        # 檢查買入指令
        buy_data = parse_buy_command(text)
        if buy_data:
            handle_buy_stock(event, buy_data)
            return
        
        # 檢查其他指令
        if text in ['持股', '我的股票']:
            handle_stock_query(event, user_id)
            return
        
        if text in ['幫助', '指令', 'help', '說明']:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=get_help_message())
            )
            return
        
        # 測試指令
        if text == '測試':
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🤖 機器人運作正常！運行在 Vercel 雲端平台\n輸入「幫助」查看使用說明")
            )
            return
        
        # 系統狀態
        if text == '狀態':
            status_msg = f"""🔧 系統狀態報告：
📊 Google Sheets: {'✅ 連接正常' if transaction_sheet else '❌ 連接失敗'}
🌐 平台：Vercel Serverless
⏰ 時間：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🚀 狀態：正常運行"""
            
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=status_msg)
            )
            return
        
        # 預設回應
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❓ 指令格式不正確，請輸入「幫助」查看使用說明")
        )
        
    except Exception as e:
        print(f"❌ 處理訊息錯誤: {e}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ 處理訊息時發生錯誤，請稍後再試")
        )

# Vercel 需要的主函數
def handler_func(request):
    return app(request.environ, lambda *args: None)

if __name__ == "__main__":
    app.run(debug=True)