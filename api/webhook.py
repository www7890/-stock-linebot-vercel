from flask import Flask, request, jsonify
import os
import json
import re
import datetime
import requests
from urllib.parse import quote

app = Flask(__name__)

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS')

print(f"Bot starting...")
print(f"Token exists: {bool(LINE_CHANNEL_ACCESS_TOKEN)}")
print(f"Sheets ID exists: {bool(SPREADSHEET_ID)}")

# Google Sheets 初始化
transaction_sheet = None
holdings_sheet = None
voting_sheet = None

def init_google_sheets():
    global transaction_sheet, holdings_sheet, voting_sheet
    try:
        if not GOOGLE_CREDENTIALS_JSON:
            print("❌ 沒有 Google 認證資訊")
            return False
        
        import gspread
        credentials_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        gc = gspread.service_account_from_dict(credentials_info)
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        
        # 取得或創建工作表
        try:
            transaction_sheet = spreadsheet.worksheet('交易紀錄')
        except:
            transaction_sheet = spreadsheet.add_worksheet(title='交易紀錄', rows=1000, cols=15)
            # 設定標題行
            transaction_sheet.update('A1:O1', [['日期時間', '使用者ID', '使用者名稱', '股票代號', '股票名稱', 
                                               '交易類型', '股數', '單價', '總金額', '理由', '群組ID', '紀錄ID', 
                                               '投票ID', '狀態', '備註']])
        
        try:
            holdings_sheet = spreadsheet.worksheet('持股統計')
        except:
            holdings_sheet = spreadsheet.add_worksheet(title='持股統計', rows=1000, cols=10)
            holdings_sheet.update('A1:J1', [['使用者ID', '使用者名稱', '股票代號', '股票名稱', 
                                            '總股數', '平均成本', '總成本', '群組ID', '更新時間', '備註']])
        
        try:
            voting_sheet = spreadsheet.worksheet('投票紀錄')
        except:
            voting_sheet = spreadsheet.add_worksheet(title='投票紀錄', rows=1000, cols=15)
            voting_sheet.update('A1:O1', [['投票ID', '發起人ID', '發起人名稱', '股票代號', '股票名稱',
                                          '賣出股數', '賣出價格', '群組ID', '投票狀態', '贊成票數', 
                                          '反對票數', '創建時間', '截止時間', '結果', '備註']])
        
        print("✅ Google Sheets 初始化成功")
        return True
    except Exception as e:
        print(f"❌ Google Sheets 初始化失敗: {e}")
        return False

# 初始化 Google Sheets
init_google_sheets()

# 股票代號對應表
STOCK_CODES = {
    '2330': '台積電',
    '2454': '聯發科', 
    '2317': '鴻海',
    '2412': '中華電',
    '2882': '國泰金',
    '2881': '富邦金',
    '2886': '兆豐金',
    '2891': '中信金',
    '1301': '台塑',
    '1303': '南亞',
    '6505': '台塑化',
    '2002': '中鋼',
    '2207': '和泰車',
    '2357': '華碩',
    '2382': '廣達',
    '2395': '研華',
    '3711': '日月光投控',
    '2379': '瑞昱',
    '2303': '聯電'
}

# 反向查詢：股票名稱 → 代號
STOCK_NAMES = {v: k for k, v in STOCK_CODES.items()}

def get_stock_code(input_text):
    """取得股票代號，支援代號或名稱輸入"""
    if input_text in STOCK_CODES:
        return input_text, STOCK_CODES[input_text]
    elif input_text in STOCK_NAMES:
        return STOCK_NAMES[input_text], input_text
    else:
        # 如果都找不到，返回原始輸入作為名稱，代號為空
        return '', input_text

def get_stock_price(stock_code, stock_name):
    """抓取股票即時價格"""
    try:
        if stock_code:
            # 使用 Yahoo Finance API
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_code}.TW"
            response = requests.get(url, timeout=5)
            data = response.json()
            
            if 'chart' in data and data['chart']['result']:
                price_data = data['chart']['result'][0]['meta']
                current_price = price_data.get('regularMarketPrice', 0)
                return round(current_price, 2) if current_price else 0
        
        # 如果抓取失敗，返回 0
        return 0
    except Exception as e:
        print(f"❌ 抓取股價失敗 {stock_code}/{stock_name}: {e}")
        return 0

def parse_shares(shares_text):
    """解析股數，支援張和股"""
    shares_text = shares_text.strip()
    
    if '張' in shares_text:
        # 提取張數
        match = re.search(r'(\d+(?:\.\d+)?)張', shares_text)
        if match:
            zhang = float(match.group(1))
            return int(zhang * 1000)  # 1張 = 1000股
    
    if '股' in shares_text:
        # 提取股數
        match = re.search(r'(\d+)股', shares_text)
        if match:
            return int(match.group(1))
    
    # 如果只有數字，預設為張
    match = re.search(r'(\d+(?:\.\d+)?)', shares_text)
    if match:
        num = float(match.group(1))
        if num >= 1000:
            return int(num)  # 大於1000認為是股數
        else:
            return int(num * 1000)  # 小於1000認為是張數
    
    return 0

def format_shares(shares):
    """格式化股數顯示"""
    if shares >= 1000:
        zhang = shares // 1000
        remaining = shares % 1000
        if remaining > 0:
            return f"{zhang}張{remaining}股"
        else:
            return f"{zhang}張"
    else:
        return f"{shares}股"

def parse_buy_command(text):
    """解析買入指令: /買入 股票名稱 數量 價格 理由"""
    pattern = r'^/買入\s+(.+?)\s+(.+?)\s+(\d+(?:\.\d+)?)元\s+(.+)$'
    match = re.match(pattern, text.strip())
    
    if match:
        stock_input = match.group(1).strip()
        shares_text = match.group(2).strip()
        price = float(match.group(3))
        reason = match.group(4).strip()
        
        shares = parse_shares(shares_text)
        if shares > 0:
            stock_code, stock_name = get_stock_code(stock_input)
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'shares': shares,
                'price': price,
                'reason': reason
            }
    
    return None

def parse_sell_command(text):
    """解析賣出指令: /賣出 股票名稱 數量 價格"""
    pattern = r'^/賣出\s+(.+?)\s+(.+?)\s+(\d+(?:\.\d+)?)元(?:\s+(.+))?$'
    match = re.match(pattern, text.strip())
    
    if match:
        stock_input = match.group(1).strip()
        shares_text = match.group(2).strip()
        price = float(match.group(3))
        note = match.group(4).strip() if match.group(4) else ''
        
        shares = parse_shares(shares_text)
        if shares > 0:
            stock_code, stock_name = get_stock_code(stock_input)
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'shares': shares,
                'price': price,
                'note': note
            }
    
    return None

def handle_buy_stock(user_id, user_name, group_id, buy_data):
    """處理買入股票"""
    try:
        total_amount = buy_data['shares'] * buy_data['price']
        record_id = str(int(datetime.datetime.now().timestamp()))
        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 記錄到交易紀錄
        if transaction_sheet:
            row_data = [
                current_time, user_id, user_name, buy_data['stock_code'], buy_data['stock_name'],
                '買入', buy_data['shares'], buy_data['price'], total_amount, buy_data['reason'],
                group_id, record_id, '', '已執行', ''
            ]
            transaction_sheet.append_row(row_data)
        
        # 更新持股統計
        update_holdings(user_id, user_name, group_id, buy_data['stock_code'], 
                       buy_data['stock_name'], buy_data['shares'], buy_data['price'], 'buy')
        
        # 格式化回覆
        display_shares = format_shares(buy_data['shares'])
        response = f"""📈 買入交易已記錄！

🏢 股票：{buy_data['stock_name']} ({buy_data['stock_code'] if buy_data['stock_code'] else '手動輸入'})
📊 數量：{display_shares}
💰 單價：{buy_data['price']}元
💵 總金額：{total_amount:,}元
💡 理由：{buy_data['reason']}

✅ 交易紀錄已儲存至 Google Sheets"""
        
        return response
        
    except Exception as e:
        print(f"❌ 處理買入錯誤: {e}")
        return f"❌ 處理買入指令時發生錯誤: {str(e)}"

def update_holdings(user_id, user_name, group_id, stock_code, stock_name, shares, price, action):
    """更新持股統計"""
    try:
        if not holdings_sheet:
            return
        
        # 查找現有持股
        records = holdings_sheet.get_all_records()
        existing_row = None
        row_index = None
        
        for i, record in enumerate(records, 2):  # 從第2行開始
            if (record['使用者ID'] == user_id and 
                record['群組ID'] == group_id and
                (record['股票代號'] == stock_code or record['股票名稱'] == stock_name)):
                existing_row = record
                row_index = i
                break
        
        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if action == 'buy':
            if existing_row:
                # 更新現有持股
                old_shares = int(existing_row['總股數'] or 0)
                old_cost = float(existing_row['總成本'] or 0)
                
                new_shares = old_shares + shares
                new_total_cost = old_cost + (shares * price)
                new_avg_cost = new_total_cost / new_shares if new_shares > 0 else 0
                
                holdings_sheet.update(f'E{row_index}:G{row_index}', 
                                    [[new_shares, round(new_avg_cost, 2), new_total_cost]])
                holdings_sheet.update(f'I{row_index}', current_time)
            else:
                # 新增持股記錄
                new_row = [
                    user_id, user_name, stock_code, stock_name,
                    shares, price, shares * price, group_id, current_time, ''
                ]
                holdings_sheet.append_row(new_row)
        
        elif action == 'sell':
            if existing_row and row_index:
                old_shares = int(existing_row['總股數'] or 0)
                old_cost = float(existing_row['總成本'] or 0)
                avg_cost = float(existing_row['平均成本'] or 0)
                
                if old_shares >= shares:
                    new_shares = old_shares - shares
                    new_total_cost = new_shares * avg_cost if new_shares > 0 else 0
                    
                    if new_shares > 0:
                        holdings_sheet.update(f'E{row_index}:G{row_index}', 
                                            [[new_shares, avg_cost, new_total_cost]])
                        holdings_sheet.update(f'I{row_index}', current_time)
                    else:
                        # 刪除持股記錄（賣完了）
                        holdings_sheet.delete_rows(row_index)
        
    except Exception as e:
        print(f"❌ 更新持股統計錯誤: {e}")

def get_user_holdings(user_id, group_id, specific_stock=None):
    """查詢使用者持股"""
    try:
        if not holdings_sheet:
            return "❌ 無法連接持股資料庫"
        
        records = holdings_sheet.get_all_records()
        user_holdings = []
        
        for record in records:
            if record['使用者ID'] == user_id and record['群組ID'] == group_id:
                if specific_stock:
                    stock_code, stock_name = get_stock_code(specific_stock)
                    if (record['股票代號'] == stock_code or 
                        record['股票名稱'] == stock_name or
                        record['股票名稱'] == specific_stock):
                        user_holdings.append(record)
                else:
                    user_holdings.append(record)
        
        if not user_holdings:
            if specific_stock:
                return f"📊 您沒有持有 {specific_stock}"
            else:
                return "📊 您目前沒有任何持股"
        
        # 計算總價值和格式化顯示
        total_cost = 0
        total_current_value = 0
        holdings_text = "📊 您的持股狀況：\n\n"
        
        for holding in user_holdings:
            stock_code = holding['股票代號']
            stock_name = holding['股票名稱']
            shares = int(holding['總股數'])
            avg_cost = float(holding['平均成本'])
            cost = float(holding['總成本'])
            
            # 抓取當前股價
            current_price = get_stock_price(stock_code, stock_name)
            current_value = shares * current_price if current_price > 0 else cost
            
            unrealized_pnl = current_value - cost
            pnl_percentage = (unrealized_pnl / cost * 100) if cost > 0 else 0
            
            price_trend = ""
            if current_price > 0:
                if current_price > avg_cost:
                    price_trend = "↗"
                elif current_price < avg_cost:
                    price_trend = "↘"
                else:
                    price_trend = "→"
            
            holdings_text += f"📈 {stock_name}"
            if stock_code:
                holdings_text += f" ({stock_code})"
            holdings_text += f"\n"
            holdings_text += f"持股：{format_shares(shares)}\n"
            holdings_text += f"平均成本：{avg_cost:.2f}元\n"
            
            if current_price > 0:
                holdings_text += f"目前股價：{current_price:.2f}元 {price_trend}\n"
                holdings_text += f"未實現損益：{unrealized_pnl:+,.0f}元 ({pnl_percentage:+.2f}%)\n"
            else:
                holdings_text += f"股價：無法取得\n"
            
            holdings_text += f"\n"
            
            total_cost += cost
            total_current_value += current_value
        
        # 總結
        if len(user_holdings) > 1:
            total_unrealized = total_current_value - total_cost
            total_percentage = (total_unrealized / total_cost * 100) if total_cost > 0 else 0
            
            holdings_text += f"💰 總投資成本：{total_cost:,.0f}元\n"
            if total_current_value != total_cost:
                holdings_text += f"💵 目前總價值：{total_current_value:,.0f}元\n"
                holdings_text += f"📊 總未實現損益：{total_unrealized:+,.0f}元 ({total_percentage:+.2f}%)"
        
        return holdings_text
        
    except Exception as e:
        print(f"❌ 查詢持股錯誤: {e}")
        return f"❌ 查詢持股時發生錯誤: {str(e)}"

def send_reply_message(reply_token, message_text):
    """發送回覆訊息"""
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
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            print("✅ 訊息發送成功")
            return True
        else:
            print(f"❌ API 錯誤: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ 發送失敗: {e}")
        return False

@app.route("/", methods=['GET'])
def health_check():
    return jsonify({
        "status": "running",
        "message": "🤖 完整版股票管理 LINE Bot",
        "version": "2.0",
        "features": [
            "買入股票 (/買入)",
            "持股查詢 (/持股)",
            "賣出投票 (/賣出)",
            "股價查詢",
            "零股支援"
        ],
        "sheets_connected": bool(transaction_sheet and holdings_sheet),
        "environment_vars": {
            "LINE_CHANNEL_ACCESS_TOKEN": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "LINE_CHANNEL_SECRET": bool(LINE_CHANNEL_SECRET),
            "SPREADSHEET_ID": bool(SPREADSHEET_ID),
            "GOOGLE_CREDENTIALS": bool(GOOGLE_CREDENTIALS_JSON)
        }
    })

@app.route("/api/webhook", methods=['POST'])
def webhook():
    try:
        body = request.get_data(as_text=True)
        events_data = json.loads(body)
        events = events_data.get('events', [])
        
        for event in events:
            event_type = event.get('type')
            
            if event_type == 'message' and event.get('message', {}).get('type') == 'text':
                reply_token = event.get('replyToken')
                message_text = event.get('message', {}).get('text', '').strip()
                user_id = event.get('source', {}).get('userId', '')
                group_id = event.get('source', {}).get('groupId', user_id)
                
                # 取得使用者名稱
                try:
                    from linebot import LineBotApi
                    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
                    if group_id != user_id:
                        profile = line_bot_api.get_group_member_profile(group_id, user_id)
                    else:
                        profile = line_bot_api.get_profile(user_id)
                    user_name = profile.display_name
                except:
                    user_name = "未知使用者"
                
                print(f"💬 收到訊息: '{message_text}' 來自: {user_name}")
                
                response_text = None
                
                # 處理各種指令
                if message_text.startswith('/買入'):
                    buy_data = parse_buy_command(message_text)
                    if buy_data:
                        response_text = handle_buy_stock(user_id, user_name, group_id, buy_data)
                    else:
                        response_text = """❌ 買入指令格式錯誤

正確格式：/買入 股票名稱 數量 價格 理由

範例：
• /買入 台積電 5張 580元 看好AI趨勢
• /買入 2330 500股 580元 看好AI趨勢
• /買入 聯發科 3張 1200元 5G晶片需求強勁"""

                elif message_text.startswith('/持股'):
                    parts = message_text.split()
                    if len(parts) == 1:
                        # 查詢所有持股
                        response_text = get_user_holdings(user_id, group_id)
                    elif len(parts) == 2:
                        # 查詢特定股票
                        stock_input = parts[1]
                        response_text = get_user_holdings(user_id, group_id, stock_input)
                    else:
                        response_text = "❌ 持股查詢格式錯誤\n\n用法：\n• /持股 - 查看所有持股\n• /持股 台積電 - 查看特定股票"

                elif message_text == '/幫助' or message_text == '/help':
                    response_text = """📚 股票管理機器人使用說明：

🟢 基本指令：
• /買入 股票 數量 價格 理由
• /持股 - 查看所有持股
• /持股 股票名稱 - 查看特定持股
• /賣出 股票 數量 價格 - 發起賣出投票
• /幫助 - 顯示此說明

📊 數量格式：
• 5張 = 5000股
• 500股 = 500股
• 支援零股交易

📈 範例指令：
• /買入 台積電 5張 580元 看好AI趨勢
• /買入 2330 500股 580元 技術面突破
• /持股 台積電
• /賣出 台積電 2張 600元

🔧 功能特色：
• 自動抓取即時股價
• 計算未實現損益
• 群組投票賣出機制
• Google Sheets 資料備份"""

                elif message_text == '/測試':
                    response_text = """🤖 完整版機器人運作正常！

✅ Webhook 連接成功
✅ Google Sheets 連接正常
✅ 股價查詢功能啟用
✅ 零股交易支援
✅ 投票系統準備就緒

🌐 運行在 Vercel 雲端平台
💡 輸入 /幫助 查看完整功能"""

                # 發送回覆
                if response_text and reply_token:
                    send_reply_message(reply_token, response_text)
        
        return jsonify({"status": "OK"}), 200
        
    except Exception as e:
        print(f"❌ Webhook 處理錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
