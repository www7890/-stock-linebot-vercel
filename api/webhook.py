from flask import Flask, request, jsonify
import os
import json
import re
import datetime
import requests
from urllib.parse import quote
import time
import uuid
from datetime import datetime, timedelta

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

# 儲存進行中的投票（實際部署應該用資料庫）
active_votes = {}
user_daily_votes = {}

# 股票清單快取（動態爬取後儲存）
STOCK_CODES = {}
STOCK_NAMES = {}
STOCK_CACHE_TIME = None
CACHE_DURATION = 3600  # 快取1小時

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

def get_fallback_stock_list():
    """備用股票清單（基本的熱門股票）"""
    return {
        # 熱門上市股票
        '2330': '台積電',
        '2454': '聯發科',
        '2317': '鴻海',
        '2412': '中華電',
        '2882': '國泰金',
        '2881': '富邦金',
        '2886': '兆豐金',
        '2891': '中信金',
        '2308': '台達電',
        '2303': '聯電',
        '2603': '長榮',
        '2609': '陽明',
        '2615': '萬海',
        '3008': '大立光',
        '2002': '中鋼',
        '2357': '華碩',
        '2382': '廣達',
        '1301': '台塑',
        '1303': '南亞',
        '2884': '玉山金',
        '2885': '元大金',
        '2892': '第一金',
        '6505': '台塑化',
        '2207': '和泰車',
        '2395': '研華',
        '3711': '日月光投控',
        '2379': '瑞昱',
        '2327': '國巨',
        '2345': '智邦',
        '2377': '微星',
        '1216': '統一',
        '1229': '聯華',
        '2912': '統一超',
        '9910': '豐泰',
        '2887': '台新金',
        '2890': '永豐金',
        
        # 熱門上櫃股票
        '3078': '波若威',
        '6547': '高端疫苗',
        '3105': '穩懋',
        '5274': '信驊',
        '3661': '世芯-KY',
        '6488': '環球晶',
        '8299': '群聯',
        '3293': '鈊象',
        '5483': '中美晶',
        '3260': '威剛',
        '6121': '新普',
        '6147': '頎邦',
        '8086': '宏捷科',
        '4966': '譜瑞-KY',
        '3227': '原相',
        '3707': '漢磊',
        '5269': '祥碩',
        '3529': '力旺',
        '6104': '創惟',
        '3680': '家登',
        '5347': '世界',
        '3324': '雙鴻',
        '6510': '精測',
        '3141': '晶宏',
        '6732': 'M31',
        '3217': '優群',
        '4743': '合一',
        '4174': '浩鼎',
        '1565': '精華',
        '4123': '晟德',
        '6469': '大樹'
    }

def init_stock_list():
    """初始化股票清單"""
    global STOCK_CODES, STOCK_NAMES
    # 先使用基本清單，確保程式可以運作
    STOCK_CODES = get_fallback_stock_list()
    STOCK_NAMES = {v: k for k, v in STOCK_CODES.items()}
    print(f"初始化基本股票清單: {len(STOCK_CODES)} 支")
    # 背景嘗試載入完整清單
    try:
        fetch_stock_list()
    except Exception as e:
        print(f"背景載入股票清單失敗: {e}")

def fetch_stock_list():
    """動態爬取所有上市櫃股票清單"""
    global STOCK_CODES, STOCK_NAMES, STOCK_CACHE_TIME
    
    # 檢查快取是否有效
    if STOCK_CACHE_TIME and STOCK_CODES:
        if time.time() - STOCK_CACHE_TIME < CACHE_DURATION:
            print(f"使用快取的股票清單，共 {len(STOCK_CODES)} 支股票")
            return True
    
    print("開始動態爬取股票清單...")
    temp_codes = {}
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # 方法1: 使用更可靠的 API endpoint
        try:
            # 取得所有上市股票
            print("爬取上市股票...")
            tse_url = "https://www.twse.com.tw/rwd/zh/api/codeQuery?query="
            response = requests.get(tse_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'suggestions' in data:
                    for item in data['suggestions']:
                        # 格式: "2330\t台積電"
                        if '\t' in item:
                            parts = item.split('\t')
                            if len(parts) >= 2:
                                code = parts[0].strip()
                                name = parts[1].strip().split('(')[0].strip()  # 移除括號內容
                                if code and name and code[0].isdigit():
                                    temp_codes[code] = name
            
            # 取得所有上櫃股票
            print("爬取上櫃股票...")
            otc_url = "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&se=AL"
            response = requests.get(otc_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'aaData' in data:
                    for item in data['aaData']:
                        if len(item) >= 2:
                            code = str(item[0]).strip()
                            name = str(item[1]).strip()
                            if code and name and code[0].isdigit():
                                temp_codes[code] = name
                                
        except Exception as e:
            print(f"方法1失敗: {e}")
        
        # 方法2: 備用爬取方式
        if len(temp_codes) < 100:
            print("使用備用爬取方式...")
            try:
                # 從證交所網站取得股票清單
                import re
                
                # 上市股票
                url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    response.encoding = 'big5'
                    html = response.text
                    # 簡單的正則表達式解析
                    pattern = r'<td.*?>(\d{4,6})\s+([\u4e00-\u9fa5\w\-]+)</td>'
                    matches = re.findall(pattern, html)
                    for code, name in matches:
                        if code and name and code[0].isdigit():
                            temp_codes[code] = name.strip()
                
                # 上櫃股票
                url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    response.encoding = 'big5'
                    html = response.text
                    pattern = r'<td.*?>(\d{4,6})\s+([\u4e00-\u9fa5\w\-]+)</td>'
                    matches = re.findall(pattern, html)
                    for code, name in matches:
                        if code and name and code[0].isdigit():
                            temp_codes[code] = name.strip()
                            
            except Exception as e:
                print(f"方法2失敗: {e}")
        
        # 如果爬取失敗或數量太少，使用備用清單
        if len(temp_codes) < 50:
            print("爬取數量不足，使用備用清單...")
            temp_codes = get_fallback_stock_list()
        
        # 更新全域變數
        if temp_codes:
            STOCK_CODES = temp_codes
            STOCK_NAMES = {v: k for k, v in STOCK_CODES.items()}
            STOCK_CACHE_TIME = time.time()
            print(f"✅ 成功載入 {len(STOCK_CODES)} 支股票")
            
            # 儲存到 Google Sheets 作為備份（選擇性）
            try:
                save_stock_list_to_sheets(STOCK_CODES)
            except:
                pass
                
            return True
        else:
            print("❌ 無法取得股票清單，使用基本清單")
            STOCK_CODES = get_fallback_stock_list()
            STOCK_NAMES = {v: k for k, v in STOCK_CODES.items()}
            return False
            
    except Exception as e:
        print(f"爬取股票清單錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        # 發生錯誤時使用備用清單
        STOCK_CODES = get_fallback_stock_list()
        STOCK_NAMES = {v: k for k, v in STOCK_CODES.items()}
        return False

def save_stock_list_to_sheets(stock_dict):
    """將股票清單儲存到 Google Sheets（選擇性功能）"""
    try:
        if not GOOGLE_CREDENTIALS_JSON or not SPREADSHEET_ID:
            return
        
        import gspread
        credentials_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        gc = gspread.service_account_from_dict(credentials_info)
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        
        # 嘗試取得或創建股票清單工作表
        try:
            stock_list_sheet = spreadsheet.worksheet('股票清單')
            stock_list_sheet.clear()
        except:
            stock_list_sheet = spreadsheet.add_worksheet(title='股票清單', rows=5000, cols=3)
        
        # 準備資料
        headers = [['股票代號', '股票名稱', '更新時間']]
        data = []
        update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        for code, name in sorted(stock_dict.items()):
            data.append([code, name, update_time])
        
        # 寫入資料
        if data:
            stock_list_sheet.update('A1:C1', headers)
            stock_list_sheet.update(f'A2:C{len(data)+1}', data)
            print(f"✅ 股票清單已儲存到 Google Sheets")
            
    except Exception as e:
        print(f"儲存股票清單到 Sheets 失敗: {e}")

def search_stock_from_web(keyword):
    """從網路即時搜尋股票代號和名稱"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        print(f"開始網路搜尋: {keyword}")
        
        # 使用證交所的搜尋 API
        search_url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
        
        # 如果是數字，可能是股票代號
        if keyword.isdigit():
            # 嘗試上市股票
            params = {'ex_ch': f'tse_{keyword}.tw', 'json': '1', 'delay': '0'}
            response = requests.get(search_url, params=params, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'msgArray' in data and len(data['msgArray']) > 0:
                    stock_data = data['msgArray'][0]
                    if 'c' in stock_data and 'n' in stock_data:
                        code = stock_data['c']
                        name = stock_data['n']
                        print(f"找到上市股票: {code} {name}")
                        return code, name
            
            # 嘗試上櫃股票
            params = {'ex_ch': f'otc_{keyword}.tw', 'json': '1', 'delay': '0'}
            response = requests.get(search_url, params=params, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'msgArray' in data and len(data['msgArray']) > 0:
                    stock_data = data['msgArray'][0]
                    if 'c' in stock_data and 'n' in stock_data:
                        code = stock_data['c']
                        name = stock_data['n']
                        print(f"找到上櫃股票: {code} {name}")
                        return code, name
        
        print(f"網路搜尋無結果: {keyword}")
        return None, keyword
        
    except Exception as e:
        print(f"搜尋股票錯誤: {e}")
        return None, keyword

# 初始化 Google Sheets
init_google_sheets()

# 初始化股票清單
init_stock_list()

def get_stock_code(input_text):
    """取得股票代號，支援代號或名稱輸入（動態查詢）"""
    input_text = input_text.strip()
    
    # 確保股票清單已載入
    if not STOCK_CODES:
        init_stock_list()
    
    # 先嘗試直接匹配代號
    if input_text in STOCK_CODES:
        return input_text, STOCK_CODES[input_text]
    
    # 再嘗試匹配名稱
    if input_text in STOCK_NAMES:
        return STOCK_NAMES[input_text], input_text
    
    # 嘗試部分匹配名稱
    for name, code in STOCK_NAMES.items():
        if input_text in name or name in input_text:
            return code, name
    
    # 如果本地找不到，嘗試從網路搜尋
    print(f"本地找不到 {input_text}，嘗試網路搜尋...")
    code, name = search_stock_from_web(input_text)
    
    # 如果找到了，加入快取
    if code and code != input_text:
        STOCK_CODES[code] = name
        STOCK_NAMES[name] = code
        print(f"✅ 找到並快取: {code} {name}")
        return code, name
    
    # 如果都找不到，返回原始輸入作為名稱，代號為空
    return '', input_text

def get_stock_price_yahoo(stock_code):
    """使用 Yahoo Finance API 抓取股價（支援上市上櫃）"""
    try:
        # 上市股票用 .TW，上櫃股票用 .TWO
        suffixes = ['.TW', '.TWO']
        
        for suffix in suffixes:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_code}{suffix}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'chart' in data and data['chart']['result']:
                    result = data['chart']['result'][0]
                    if 'meta' in result and 'regularMarketPrice' in result['meta']:
                        price = result['meta']['regularMarketPrice']
                        print(f"✅ Yahoo Finance 成功 ({stock_code}{suffix}): {price}")
                        return round(float(price), 2)
        
        return None
    except Exception as e:
        print(f"Yahoo Finance 錯誤 {stock_code}: {e}")
        return None

def get_stock_price_twse(stock_code):
    """使用 TWSE/TPEx API 抓取股價（支援上市上櫃）"""
    try:
        # 先嘗試上市（TWSE）
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
        params = {
            'ex_ch': f'tse_{stock_code}.tw',
            'json': '1',
            'delay': '0'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://mis.twse.com.tw/'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if 'msgArray' in data and len(data['msgArray']) > 0:
                stock_data = data['msgArray'][0]
                if 'z' in stock_data and stock_data['z'] != '-':
                    print(f"✅ TWSE API 成功 (上市): {stock_data['z']}")
                    return float(stock_data['z'])
                elif 'y' in stock_data and stock_data['y'] != '-':
                    print(f"✅ TWSE API 成功 (上市昨收): {stock_data['y']}")
                    return float(stock_data['y'])
        
        # 再嘗試上櫃（TPEx）
        params['ex_ch'] = f'otc_{stock_code}.tw'
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if 'msgArray' in data and len(data['msgArray']) > 0:
                stock_data = data['msgArray'][0]
                if 'z' in stock_data and stock_data['z'] != '-':
                    print(f"✅ TPEx API 成功 (上櫃): {stock_data['z']}")
                    return float(stock_data['z'])
                elif 'y' in stock_data and stock_data['y'] != '-':
                    print(f"✅ TPEx API 成功 (上櫃昨收): {stock_data['y']}")
                    return float(stock_data['y'])
        
        return None
    except Exception as e:
        print(f"TWSE/TPEx API 錯誤 {stock_code}: {e}")
        return None

def get_stock_price(stock_code, stock_name):
    """抓取股票即時價格（多重來源）"""
    if not stock_code:
        print(f"⚠️ 無股票代號：{stock_name}")
        # 嘗試搜尋股票代號
        code, name = search_stock_from_web(stock_name)
        if code:
            stock_code = code
            stock_name = name
            print(f"✅ 找到股票代號: {stock_code} {stock_name}")
        else:
            return 0
    
    print(f"📊 開始抓取股價：{stock_code} {stock_name}")
    
    # 策略1: Yahoo Finance
    price = get_stock_price_yahoo(stock_code)
    if price and price > 0:
        print(f"✅ Yahoo Finance 成功：{price}")
        return price
    
    # 策略2: TWSE API
    time.sleep(0.5)
    price = get_stock_price_twse(stock_code)
    if price and price > 0:
        print(f"✅ TWSE API 成功：{price}")
        return price
    
    print(f"❌ 無法取得股價: {stock_code} {stock_name}")
    return 0

def parse_shares(shares_text):
    """解析股數，支援張和股"""
    shares_text = shares_text.strip()
    
    if '張' in shares_text:
        match = re.search(r'(\d+(?:\.\d+)?)張', shares_text)
        if match:
            zhang = float(match.group(1))
            return int(zhang * 1000)
    
    if '股' in shares_text:
        match = re.search(r'(\d+)股', shares_text)
        if match:
            return int(match.group(1))
    
    # 只有數字
    match = re.search(r'(\d+(?:\.\d+)?)', shares_text)
    if match:
        num = float(match.group(1))
        if num >= 1000:
            return int(num)
        else:
            return int(num * 1000)
    
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
    """解析買入指令（支援單筆和批次，不需要@）"""
    try:
        # 移除開頭的 /買入
        text = text[3:].strip()
        
        # 分離股票名稱
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return None
        
        stock_input = parts[0]
        remaining = parts[1]
        
        # 先嘗試批次模式：數量 價格 的配對（可能有多個）
        batch_pattern = r'(\d+(?:\.\d+)?)\s*(張|股)?\s+(\d+(?:\.\d+)?)\s*元'
        matches = re.findall(batch_pattern, remaining)
        
        # 如果找到2個或以上匹配，視為批次交易
        if len(matches) >= 2:
            # 找出理由（在最後一個價格之後的文字）
            last_match = matches[-1]
            last_pattern = f"{last_match[0]}\\s*{last_match[1] if last_match[1] else ''}\\s+{last_match[2]}\\s*元"
            
            last_match_obj = None
            for match_obj in re.finditer(last_pattern, remaining):
                last_match_obj = match_obj
            
            if last_match_obj:
                reason_start = last_match_obj.end()
                reason = remaining[reason_start:].strip() if reason_start < len(remaining) else "批次買入"
            else:
                reason = "批次買入"
            
            # 處理每個價格區間
            stock_code, stock_name = get_stock_code(stock_input)
            transactions = []
            total_shares = 0
            total_amount = 0
            
            for match in matches:
                quantity = float(match[0])
                unit = match[1] if match[1] else ''
                price = float(match[2])
                
                if unit == '股':
                    shares = int(quantity)
                elif unit == '張':
                    shares = int(quantity * 1000)
                else:
                    if quantity >= 1000:
                        shares = int(quantity)
                    else:
                        shares = int(quantity * 1000)
                
                amount = shares * price
                total_shares += shares
                total_amount += amount
                
                transactions.append({
                    'shares': shares,
                    'price': price,
                    'amount': amount
                })
            
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'transactions': transactions,
                'total_shares': total_shares,
                'total_amount': total_amount,
                'avg_price': total_amount / total_shares if total_shares > 0 else 0,
                'reason': reason,
                'is_batch': True
            }
        
        # 單一價格格式：嘗試多種解析方式
        # 格式1: 1張 1200元 理由
        pattern1 = r'^(\d+(?:\.\d+)?)\s*(張|股)?\s+(\d+(?:\.\d+)?)\s*元\s+(.*)$'
        match1 = re.match(pattern1, remaining)
        
        if match1:
            quantity = float(match1.group(1))
            unit = match1.group(2) if match1.group(2) else ''
            price = float(match1.group(3))
            reason = match1.group(4).strip() if match1.group(4) else '無理由'
            
            # 計算股數
            if unit == '股':
                shares = int(quantity)
            elif unit == '張':
                shares = int(quantity * 1000)
            else:
                # 沒有單位時，小於1000視為張
                if quantity < 1000:
                    shares = int(quantity * 1000)
                else:
                    shares = int(quantity)
            
            stock_code, stock_name = get_stock_code(stock_input)
            
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'shares': shares,
                'price': price,
                'reason': reason,
                'is_batch': False
            }
        
        # 格式2: 5張 580元 (沒有理由)
        pattern2 = r'^(\d+(?:\.\d+)?)\s*(張|股)?\s+(\d+(?:\.\d+)?)\s*元\s*$'
        match2 = re.match(pattern2, remaining)
        
        if match2:
            quantity = float(match2.group(1))
            unit = match2.group(2) if match2.group(2) else ''
            price = float(match2.group(3))
            
            if unit == '股':
                shares = int(quantity)
            elif unit == '張':
                shares = int(quantity * 1000)
            else:
                if quantity < 1000:
                    shares = int(quantity * 1000)
                else:
                    shares = int(quantity)
            
            stock_code, stock_name = get_stock_code(stock_input)
            
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'shares': shares,
                'price': price,
                'reason': '無特定理由',
                'is_batch': False
            }
        
        return None
        
    except Exception as e:
        print(f"解析買入錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return None

def parse_sell_command(text):
    """解析賣出指令（支援單筆和批次，不需要@）"""
    try:
        text = text[3:].strip()
        parts = text.split(maxsplit=1)
        
        if len(parts) < 2:
            return None
        
        stock_input = parts[0]
        remaining = parts[1]
        
        # 先嘗試批次模式：數量 價格 的配對（可能有多個）
        batch_pattern = r'(\d+(?:\.\d+)?)\s*(張|股)?\s+(\d+(?:\.\d+)?)\s*元'
        matches = re.findall(batch_pattern, remaining)
        
        # 如果找到2個或以上匹配，視為批次交易
        if len(matches) >= 2:
            # 找備註
            last_match = matches[-1]
            last_pattern = f"{last_match[0]}\\s*{last_match[1] if last_match[1] else ''}\\s+{last_match[2]}\\s*元"
            
            last_match_obj = None
            for match_obj in re.finditer(last_pattern, remaining):
                last_match_obj = match_obj
            
            if last_match_obj:
                note_start = last_match_obj.end()
                note = remaining[note_start:].strip() if note_start < len(remaining) else ""
            else:
                note = ""
            
            stock_code, stock_name = get_stock_code(stock_input)
            transactions = []
            total_shares = 0
            total_amount = 0
            
            for match in matches:
                quantity = float(match[0])
                unit = match[1] if match[1] else ''
                price = float(match[2])
                
                if unit == '股':
                    shares = int(quantity)
                elif unit == '張':
                    shares = int(quantity * 1000)
                else:
                    if quantity >= 1000:
                        shares = int(quantity)
                    else:
                        shares = int(quantity * 1000)
                
                amount = shares * price
                total_shares += shares
                total_amount += amount
                
                transactions.append({
                    'shares': shares,
                    'price': price,
                    'amount': amount
                })
            
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'transactions': transactions,
                'total_shares': total_shares,
                'total_amount': total_amount,
                'avg_price': total_amount / total_shares if total_shares > 0 else 0,
                'price': total_amount / total_shares if total_shares > 0 else 0,  # 相容性
                'note': note,
                'is_batch': True
            }
        
        # 單一價格格式：嘗試多種解析方式
        # 格式1: 500股 1150元 停損
        pattern1 = r'^(\d+(?:\.\d+)?)\s*(張|股)?\s+(\d+(?:\.\d+)?)\s*元\s*(.*)$'
        match1 = re.match(pattern1, remaining)
        
        if match1:
            quantity = float(match1.group(1))
            unit = match1.group(2) if match1.group(2) else ''
            price = float(match1.group(3))
            note = match1.group(4).strip() if match1.group(4) else ''
            
            # 計算股數
            if unit == '股':
                shares = int(quantity)
            elif unit == '張':
                shares = int(quantity * 1000)
            else:
                # 沒有單位時，小於1000視為張
                if quantity < 1000:
                    shares = int(quantity * 1000)
                else:
                    shares = int(quantity)
            
            stock_code, stock_name = get_stock_code(stock_input)
            
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'shares': shares,
                'price': price,
                'note': note,
                'is_batch': False,
                'total_shares': shares,  # 加入 total_shares
                'avg_price': price  # 加入 avg_price
            }
        
        # 格式2: 2張 600元 (沒有備註)
        pattern2 = r'^(\d+(?:\.\d+)?)\s*(張|股)?\s+(\d+(?:\.\d+)?)\s*元\s*$'
        match2 = re.match(pattern2, remaining)
        
        if match2:
            quantity = float(match2.group(1))
            unit = match2.group(2) if match2.group(2) else ''
            price = float(match2.group(3))
            
            if unit == '股':
                shares = int(quantity)
            elif unit == '張':
                shares = int(quantity * 1000)
            else:
                if quantity < 1000:
                    shares = int(quantity * 1000)
                else:
                    shares = int(quantity)
            
            stock_code, stock_name = get_stock_code(stock_input)
            
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'shares': shares,
                'price': price,
                'note': '',
                'is_batch': False,
                'total_shares': shares,  # 加入 total_shares
                'avg_price': price  # 加入 avg_price
            }
        
        return None
        
    except Exception as e:
        print(f"解析賣出錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return None

def handle_buy_stock(user_id, user_name, group_id, buy_data):
    """處理買入股票（修復版 - 加強錯誤處理）"""
    try:
        # 基本資料驗證
        if not buy_data:
            return "❌ 買入資料為空"
        
        # 取得基本資料
        shares = buy_data.get('shares', 0)
        price = buy_data.get('price', 0)
        stock_code = buy_data.get('stock_code', '')
        stock_name = buy_data.get('stock_name', '未知股票')
        reason = buy_data.get('reason', '無理由')
        is_batch = buy_data.get('is_batch', False)
        transactions = buy_data.get('transactions', [])
        
        # 如果是批次交易
        if is_batch and len(transactions) > 1:
            return handle_batch_buy_stock(user_id, user_name, group_id, buy_data)
        
        # 驗證數值
        if shares <= 0:
            return "❌ 股數必須大於0"
        if price <= 0:
            return "❌ 價格必須大於0"
        
        total_amount = shares * price
        record_id = str(int(datetime.now().timestamp()))
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 嘗試記錄到 Google Sheets
        sheets_success = False
        if transaction_sheet:
            try:
                row_data = [
                    current_time,
                    str(user_id),
                    str(user_name),
                    str(stock_code),
                    str(stock_name),
                    '買入',
                    int(shares),
                    float(price),
                    float(total_amount),
                    str(reason),
                    str(group_id),
                    str(record_id),
                    '',
                    '已執行',
                    ''
                ]
                transaction_sheet.append_row(row_data)
                sheets_success = True
                print(f"✅ 交易已記錄到 Google Sheets")
            except Exception as e:
                print(f"⚠️ Google Sheets 記錄失敗: {e}")
                sheets_success = False
        
        # 嘗試更新持股
        holdings_updated = False
        try:
            update_holdings(user_id, user_name, group_id, stock_code, 
                          stock_name, shares, price, 'buy')
            holdings_updated = True
            print(f"✅ 持股已更新")
        except Exception as e:
            print(f"⚠️ 持股更新失敗: {e}")
            holdings_updated = False
        
        # 產生回應訊息
        display_shares = format_shares(shares)
        response = f"""📈 買入交易已處理！

🏢 股票：{stock_name} ({stock_code if stock_code else '手動輸入'})
📊 數量：{display_shares}
💰 單價：{price:.2f}元
💵 總金額：{total_amount:,.0f}元
💡 理由：{reason}"""
        
        # 加上狀態提示
        if sheets_success and holdings_updated:
            response += "\n\n✅ 交易已完整記錄"
        elif sheets_success:
            response += "\n\n✅ 交易已記錄（持股更新失敗）"
        elif holdings_updated:
            response += "\n\n⚠️ 已更新持股（交易記錄失敗）"
        else:
            response += "\n\n⚠️ 交易已接收但記錄失敗，請檢查 Google Sheets 連接"
        
        return response
        
    except Exception as e:
        print(f"❌ 處理買入錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        
        # 提供更友善的錯誤訊息
        return f"""❌ 處理買入時發生錯誤

請檢查：
1. Google Sheets 是否正確連接
2. 環境變數是否設置完整
3. 股票資訊是否正確

您可以使用 /測試 檢查系統狀態
錯誤代碼：{str(e)[:100]}"""

def handle_batch_buy_stock(user_id, user_name, group_id, buy_data):
    """處理批次買入（不同價格）"""
    try:
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        transaction_details = []
        
        # 記錄每筆交易
        for i, trans in enumerate(buy_data['transactions'], 1):
            record_id = f"{int(datetime.now().timestamp())}_{i}"
            
            if transaction_sheet:
                try:
                    row_data = [
                        current_time,
                        str(user_id),
                        str(user_name),
                        str(buy_data.get('stock_code', '')),
                        str(buy_data.get('stock_name', '未知股票')),
                        '買入',
                        int(trans.get('shares', 0)),
                        float(trans.get('price', 0)),
                        float(trans.get('amount', 0)),
                        f"{buy_data.get('reason', '批次買入')} (批次{i}/{len(buy_data['transactions'])})",
                        str(group_id),
                        str(record_id),
                        '',
                        '已執行',
                        f"批次交易第{i}筆"
                    ]
                    transaction_sheet.append_row(row_data)
                except Exception as e:
                    print(f"批次 {i} 記錄失敗: {e}")
            
            transaction_details.append(
                f"  • {format_shares(trans['shares'])} @ {trans['price']:.2f}元 = {trans['amount']:,.0f}元"
            )
        
        # 使用平均價格更新持股
        try:
            update_holdings(
                user_id, user_name, group_id,
                buy_data.get('stock_code', ''),
                buy_data.get('stock_name', '未知股票'),
                buy_data.get('total_shares', 0),
                buy_data.get('avg_price', 0),
                'buy'
            )
        except Exception as e:
            print(f"批次買入更新持股失敗: {e}")
        
        response = f"""📈 批次買入交易已記錄！

🏢 股票：{buy_data.get('stock_name', '未知')} ({buy_data.get('stock_code', 'N/A')})

📊 交易明細：
{chr(10).join(transaction_details)}

💰 總計：
  • 總股數：{format_shares(buy_data.get('total_shares', 0))}
  • 總金額：{buy_data.get('total_amount', 0):,.0f}元
  • 平均價：{buy_data.get('avg_price', 0):.2f}元

💡 理由：{buy_data.get('reason', '批次買入')}

✅ 所有交易已記錄"""
        
        return response
        
    except Exception as e:
        print(f"❌ 處理批次買入錯誤: {e}")
        return f"❌ 處理批次買入時發生錯誤: {str(e)}"

def update_holdings(user_id, user_name, group_id, stock_code, stock_name, shares, price, action):
    """更新持股統計（修復版）"""
    try:
        if not holdings_sheet:
            print("⚠️ holdings_sheet 不存在")
            return False
        
        # 安全地取得記錄
        try:
            records = holdings_sheet.get_all_records()
        except Exception as e:
            print(f"無法讀取持股記錄: {e}")
            records = []
        
        existing_row = None
        row_index = None
        
        # 查找現有持股 - 更精確的比對
        for i, record in enumerate(records, 2):
            try:
                # 確保都轉為字串比較，避免型別問題
                record_user_id = str(record.get('使用者ID', ''))
                record_group_id = str(record.get('群組ID', ''))
                record_stock_code = str(record.get('股票代號', ''))
                record_stock_name = str(record.get('股票名稱', ''))
                
                # 比對使用者和群組
                if record_user_id == str(user_id) and record_group_id == str(group_id):
                    # 比對股票（代號優先，名稱次之）
                    if stock_code and record_stock_code == str(stock_code):
                        existing_row = record
                        row_index = i
                        print(f"找到持股記錄（by代號）：第 {row_index} 行")
                        break
                    elif record_stock_name == str(stock_name):
                        existing_row = record
                        row_index = i
                        print(f"找到持股記錄（by名稱）：第 {row_index} 行")
                        break
            except Exception as e:
                print(f"比對第 {i} 行時發生錯誤: {e}")
                continue
        
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if action == 'buy':
            try:
                if existing_row:
                    # 更新現有持股
                    old_shares = float(str(existing_row.get('總股數', 0) or 0).replace(',', ''))
                    old_cost = float(str(existing_row.get('總成本', 0) or 0).replace(',', ''))
                    
                    new_shares = old_shares + shares
                    new_total_cost = old_cost + (shares * price)
                    new_avg_cost = new_total_cost / new_shares if new_shares > 0 else 0
                    
                    holdings_sheet.update(f'E{row_index}:G{row_index}', 
                                        [[int(new_shares), round(new_avg_cost, 2), round(new_total_cost, 2)]])
                    holdings_sheet.update(f'I{row_index}', [[current_time]])
                    print(f"✅ 買入更新成功：{old_shares} + {shares} = {new_shares} 股")
                else:
                    # 新增持股記錄
                    new_row = [
                        str(user_id),
                        str(user_name),
                        str(stock_code),
                        str(stock_name),
                        int(shares),
                        float(price),
                        float(shares * price),
                        str(group_id),
                        current_time,
                        ''
                    ]
                    holdings_sheet.append_row(new_row)
                    print(f"✅ 新增持股記錄：{stock_name} {shares} 股")
                
                return True
                
            except Exception as e:
                print(f"更新買入持股錯誤: {e}")
                import traceback
                print(traceback.format_exc())
                return False
        
        elif action == 'sell':
            if not existing_row or not row_index:
                print(f"❌ 找不到持股記錄來執行賣出: user={user_id}, stock={stock_code}/{stock_name}")
                return False
            
            try:
                # 取得現有股數和成本
                old_shares = float(str(existing_row.get('總股數', 0) or 0).replace(',', ''))
                avg_cost = float(str(existing_row.get('平均成本', 0) or 0).replace(',', ''))
                
                print(f"準備賣出：現有 {old_shares} 股，要賣 {shares} 股")
                
                if old_shares < shares:
                    print(f"❌ 持股不足：只有 {old_shares} 股，無法賣出 {shares} 股")
                    return False
                
                new_shares = old_shares - shares
                
                if new_shares > 0:
                    # 還有剩餘股數，更新記錄
                    new_total_cost = new_shares * avg_cost
                    print(f"更新持股：剩餘 {new_shares} 股")
                    
                    holdings_sheet.update(f'E{row_index}:G{row_index}', 
                                        [[int(new_shares), round(avg_cost, 2), round(new_total_cost, 2)]])
                    holdings_sheet.update(f'I{row_index}', [[current_time]])
                    print(f"✅ 賣出更新成功：{old_shares} - {shares} = {new_shares} 股")
                else:
                    # 賣完了，刪除整筆記錄
                    print(f"全部賣出，刪除第 {row_index} 行")
                    holdings_sheet.delete_rows(row_index)
                    print(f"✅ 持股記錄已刪除（全部賣出）")
                
                return True
                
            except Exception as e:
                print(f"賣出更新錯誤: {e}")
                import traceback
                print(traceback.format_exc())
                return False
        
        return False
        
    except Exception as e:
        print(f"❌ 更新持股統計錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return False

def get_user_holdings(user_id, group_id, specific_stock=None):
    """查詢使用者持股（支援查看他人）"""
    try:
        if not holdings_sheet:
            return "❌ 無法連接持股資料庫"
        
        records = holdings_sheet.get_all_records()
        
        # 判斷是否要查看他人持股
        target_name = None
        if specific_stock:
            # 處理特殊關鍵字
            if specific_stock == '全部':
                return get_all_group_holdings(group_id)
            
            # 檢查是否為用戶名稱（不是股票）
            stock_code, stock_name = get_stock_code(specific_stock)
            if not stock_code and specific_stock not in STOCK_CODES.values():
                # 可能是用戶名稱
                target_name = specific_stock
                return get_others_holdings(target_name, group_id)
        
        # 原本的個人持股查詢邏輯
        user_holdings = []
        for record in records:
            if record['使用者ID'] == user_id and record['群組ID'] == group_id:
                if specific_stock and not target_name:
                    stock_code, stock_name = get_stock_code(specific_stock)
                    if (record['股票代號'] == stock_code or 
                        record['股票名稱'] == stock_name or
                        record['股票名稱'] == specific_stock):
                        user_holdings.append(record)
                else:
                    user_holdings.append(record)
        
        if not user_holdings:
            if specific_stock and not target_name:
                return f"📊 您沒有持有 {specific_stock}"
            else:
                return "📊 您目前沒有任何持股"
        
        total_cost = 0
        total_current_value = 0
        holdings_text = "📊 您的持股狀況：\n\n"
        
        for holding in user_holdings:
            stock_code = holding['股票代號']
            stock_name = holding['股票名稱']
            shares = int(holding['總股數'])
            avg_cost = float(holding['平均成本'])
            cost = float(holding['總成本'])
            
            current_price = get_stock_price(stock_code, stock_name)
            
            if current_price > 0:
                current_value = shares * current_price
                unrealized_pnl = current_value - cost
                pnl_percentage = (unrealized_pnl / cost * 100) if cost > 0 else 0
                
                price_trend = ""
                if current_price > avg_cost:
                    price_trend = "📈"
                elif current_price < avg_cost:
                    price_trend = "📉"
                else:
                    price_trend = "➡️"
            else:
                current_value = cost
                unrealized_pnl = 0
                pnl_percentage = 0
                price_trend = ""
            
            holdings_text += f"{'='*25}\n"
            holdings_text += f"📌 {stock_name}"
            if stock_code:
                holdings_text += f" ({stock_code})"
            holdings_text += f"\n"
            holdings_text += f"• 持股：{format_shares(shares)}\n"
            holdings_text += f"• 平均成本：{avg_cost:.2f}元\n"
            
            if current_price > 0:
                holdings_text += f"• 目前股價：{current_price:.2f}元 {price_trend}\n"
                holdings_text += f"• 市值：{current_value:,.0f}元\n"
                
                if unrealized_pnl > 0:
                    pnl_symbol = "🟢"
                elif unrealized_pnl < 0:
                    pnl_symbol = "🔴"
                else:
                    pnl_symbol = "⚪"
                    
                holdings_text += f"• 未實現損益：{pnl_symbol} {unrealized_pnl:+,.0f}元 ({pnl_percentage:+.2f}%)\n"
            else:
                holdings_text += f"• 股價：暫時無法取得\n"
                holdings_text += f"• 成本價值：{cost:,.0f}元\n"
            
            total_cost += cost
            total_current_value += current_value
        
        if len(user_holdings) > 1:
            holdings_text += f"\n{'='*25}\n"
            holdings_text += f"📊 投資組合總結：\n"
            holdings_text += f"• 總投資成本：{total_cost:,.0f}元\n"
            
            if total_current_value != total_cost:
                holdings_text += f"• 目前總市值：{total_current_value:,.0f}元\n"
                total_unrealized = total_current_value - total_cost
                total_percentage = (total_unrealized / total_cost * 100) if total_cost > 0 else 0
                
                if total_unrealized > 0:
                    total_symbol = "🟢"
                elif total_unrealized < 0:
                    total_symbol = "🔴"
                else:
                    total_symbol = "⚪"
                    
                holdings_text += f"• 總未實現損益：{total_symbol} {total_unrealized:+,.0f}元 ({total_percentage:+.2f}%)"
        
        return holdings_text
        
    except Exception as e:
        print(f"❌ 查詢持股錯誤: {e}")
        return f"❌ 查詢持股時發生錯誤: {str(e)}"

def get_others_holdings(target_name, group_id):
    """查看指定用戶的持股"""
    try:
        if not holdings_sheet:
            return "❌ 無法連接持股資料庫"
        
        records = holdings_sheet.get_all_records()
        target_holdings = []
        target_user_id = None
        
        # 找出目標用戶的持股
        for record in records:
            if record['群組ID'] == group_id and record['使用者名稱'] == target_name:
                target_holdings.append(record)
                if not target_user_id:
                    target_user_id = record['使用者ID']
        
        if not target_holdings:
            return f"❌ 找不到用戶「{target_name}」的持股資料\n\n💡 提示：請確認名稱是否正確，或該用戶是否有持股"
        
        # 計算持股資訊
        total_cost = 0
        total_current_value = 0
        holdings_text = f"📊 {target_name} 的持股狀況：\n\n"
        
        for holding in target_holdings:
            stock_code = holding['股票代號']
            stock_name = holding['股票名稱']
            shares = int(holding['總股數'])
            avg_cost = float(holding['平均成本'])
            cost = float(holding['總成本'])
            
            current_price = get_stock_price(stock_code, stock_name)
            
            if current_price > 0:
                current_value = shares * current_price
                unrealized_pnl = current_value - cost
                pnl_percentage = (unrealized_pnl / cost * 100) if cost > 0 else 0
                
                price_trend = ""
                if current_price > avg_cost:
                    price_trend = "📈"
                elif current_price < avg_cost:
                    price_trend = "📉"
                else:
                    price_trend = "➡️"
            else:
                current_value = cost
                unrealized_pnl = 0
                pnl_percentage = 0
                price_trend = ""
            
            holdings_text += f"{'='*25}\n"
            holdings_text += f"📌 {stock_name}"
            if stock_code:
                holdings_text += f" ({stock_code})"
            holdings_text += f"\n"
            holdings_text += f"• 持股：{format_shares(shares)}\n"
            holdings_text += f"• 平均成本：{avg_cost:.2f}元\n"
            
            if current_price > 0:
                holdings_text += f"• 目前股價：{current_price:.2f}元 {price_trend}\n"
                holdings_text += f"• 市值：{current_value:,.0f}元\n"
                
                if unrealized_pnl > 0:
                    pnl_symbol = "🟢"
                elif unrealized_pnl < 0:
                    pnl_symbol = "🔴"
                else:
                    pnl_symbol = "⚪"
                    
                holdings_text += f"• 未實現損益：{pnl_symbol} {unrealized_pnl:+,.0f}元 ({pnl_percentage:+.2f}%)\n"
            else:
                holdings_text += f"• 股價：暫時無法取得\n"
                holdings_text += f"• 成本價值：{cost:,.0f}元\n"
            
            total_cost += cost
            total_current_value += current_value
        
        if len(target_holdings) > 1:
            holdings_text += f"\n{'='*25}\n"
            holdings_text += f"📊 {target_name} 的投資組合總結：\n"
            holdings_text += f"• 總投資成本：{total_cost:,.0f}元\n"
            
            if total_current_value != total_cost:
                holdings_text += f"• 目前總市值：{total_current_value:,.0f}元\n"
                total_unrealized = total_current_value - total_cost
                total_percentage = (total_unrealized / total_cost * 100) if total_cost > 0 else 0
                
                if total_unrealized > 0:
                    total_symbol = "🟢"
                elif total_unrealized < 0:
                    total_symbol = "🔴"
                else:
                    total_symbol = "⚪"
                    
                holdings_text += f"• 總未實現損益：{total_symbol} {total_unrealized:+,.0f}元 ({total_percentage:+.2f}%)"
        
        # 加上最後更新時間
        if target_holdings:
            last_update = target_holdings[0].get('更新時間', '')
            if last_update:
                holdings_text += f"\n\n⏰ 最後更新：{last_update}"
        
        return holdings_text
        
    except Exception as e:
        print(f"❌ 查詢他人持股錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return f"❌ 查詢他人持股時發生錯誤: {str(e)}"

def get_all_group_holdings(group_id):
    """查看群組所有人的持股總覽"""
    try:
        if not holdings_sheet:
            return "❌ 無法連接持股資料庫"
        
        records = holdings_sheet.get_all_records()
        
        # 整理群組內所有用戶的持股
        user_holdings_map = {}  # {user_name: {user_id, holdings: [], total_value}}
        
        for record in records:
            if record['群組ID'] == group_id:
                user_name = record['使用者名稱']
                
                if user_name not in user_holdings_map:
                    user_holdings_map[user_name] = {
                        'user_id': record['使用者ID'],
                        'holdings': [],
                        'total_cost': 0,
                        'total_value': 0
                    }
                
                stock_code = record['股票代號']
                stock_name = record['股票名稱']
                shares = int(record['總股數'])
                avg_cost = float(record['平均成本'])
                cost = float(record['總成本'])
                
                # 取得目前股價
                current_price = get_stock_price(stock_code, stock_name)
                current_value = shares * current_price if current_price > 0 else cost
                
                user_holdings_map[user_name]['holdings'].append({
                    'stock_name': stock_name,
                    'stock_code': stock_code,
                    'shares': shares,
                    'cost': cost,
                    'current_value': current_value,
                    'current_price': current_price,
                    'avg_cost': avg_cost
                })
                
                user_holdings_map[user_name]['total_cost'] += cost
                user_holdings_map[user_name]['total_value'] += current_value
        
        if not user_holdings_map:
            return "📊 群組內目前沒有任何人持有股票"
        
        # 產生報告
        response = f"📊 群組持股總覽\n"
        response += f"{'='*30}\n\n"
        
        # 統計資訊
        total_group_value = 0
        total_group_cost = 0
        stock_statistics = {}  # {stock_name: total_shares}
        
        # 依用戶顯示持股
        for user_name, data in sorted(user_holdings_map.items()):
            response += f"👤 **{user_name}**\n"
            
            # 顯示該用戶的每支股票
            for holding in data['holdings']:
                shares_display = format_shares(holding['shares'])
                response += f"  • {holding['stock_name']}: {shares_display}"
                
                if holding['current_price'] > 0:
                    pnl = holding['current_value'] - holding['cost']
                    pnl_pct = (pnl / holding['cost'] * 100) if holding['cost'] > 0 else 0
                    
                    if pnl > 0:
                        response += f" 🟢"
                    elif pnl < 0:
                        response += f" 🔴"
                    
                    response += f" ({pnl:+,.0f})"
                
                response += f"\n"
                
                # 統計股票持有情況
                stock_key = f"{holding['stock_name']} ({holding['stock_code']})" if holding['stock_code'] else holding['stock_name']
                if stock_key not in stock_statistics:
                    stock_statistics[stock_key] = 0
                stock_statistics[stock_key] += holding['shares']
            
            # 顯示該用戶的總市值
            user_pnl = data['total_value'] - data['total_cost']
            user_pnl_pct = (user_pnl / data['total_cost'] * 100) if data['total_cost'] > 0 else 0
            
            response += f"  💰 總市值：{data['total_value']:,.0f}元"
            
            if user_pnl != 0:
                if user_pnl > 0:
                    response += f" 🟢"
                else:
                    response += f" 🔴"
                response += f" ({user_pnl:+,.0f}, {user_pnl_pct:+.1f}%)"
            
            response += f"\n\n"
            
            total_group_value += data['total_value']
            total_group_cost += data['total_cost']
        
        # 群組總計
        response += f"{'='*30}\n"
        response += f"📈 **群組統計**\n"
        response += f"• 總成員數：{len(user_holdings_map)}人\n"
        response += f"• 總投資成本：{total_group_cost:,.0f}元\n"
        response += f"• 總市值：{total_group_value:,.0f}元\n"
        
        group_pnl = total_group_value - total_group_cost
        if group_pnl != 0:
            group_pnl_pct = (group_pnl / total_group_cost * 100) if total_group_cost > 0 else 0
            if group_pnl > 0:
                response += f"• 總損益：🟢 {group_pnl:+,.0f}元 ({group_pnl_pct:+.1f}%)\n"
            else:
                response += f"• 總損益：🔴 {group_pnl:+,.0f}元 ({group_pnl_pct:+.1f}%)\n"
        
        # 熱門持股TOP 5
        if stock_statistics:
            response += f"\n🏆 **熱門持股 TOP 5**\n"
            sorted_stocks = sorted(stock_statistics.items(), key=lambda x: x[1], reverse=True)[:5]
            
            for i, (stock_name, total_shares) in enumerate(sorted_stocks, 1):
                response += f"{i}. {stock_name}: {format_shares(total_shares)}\n"
        
        return response
        
    except Exception as e:
        print(f"❌ 查詢群組持股錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return f"❌ 查詢群組持股時發生錯誤: {str(e)}"

def create_sell_voting(user_id, user_name, group_id, sell_data):
    """創建賣出投票"""
    try:
        if not holdings_sheet:
            return "❌ 無法連接持股資料庫"
        
        records = holdings_sheet.get_all_records()
        user_holding = None
        
        for record in records:
            if (record['使用者ID'] == user_id and 
                record['群組ID'] == group_id and
                (record['股票代號'] == sell_data['stock_code'] or 
                 record['股票名稱'] == sell_data['stock_name'])):
                user_holding = record
                break
        
        if not user_holding:
            return f"❌ 您沒有持有 {sell_data['stock_name']}"
        
        current_shares = int(user_holding['總股數'])
        sell_shares = sell_data.get('total_shares', sell_data.get('shares', 0))
        
        if current_shares < sell_shares:
            return f"❌ 持股不足！\n您只有 {format_shares(current_shares)}，無法賣出 {format_shares(sell_shares)}"
        
        # 取得群組成員數
        group_member_count = get_group_member_count(group_id, user_id)
        
        vote_id = str(uuid.uuid4())[:8]
        current_time = datetime.now()
        deadline = current_time + timedelta(hours=24)
        
        # 處理批次或單一價格
        if sell_data.get('is_batch') and len(sell_data.get('transactions', [])) > 1:
            price_info = json.dumps([
                {'shares': t['shares'], 'price': t['price']} 
                for t in sell_data['transactions']
            ])
            display_price = sell_data.get('avg_price', sell_data.get('price', 0))
        else:
            price_info = str(sell_data.get('price', 0))
            display_price = sell_data.get('price', sell_data.get('avg_price', 0))
        
        if voting_sheet:
            try:
                vote_data = [
                    vote_id, user_id, user_name, sell_data['stock_code'], sell_data['stock_name'],
                    sell_shares, display_price, group_id, '進行中', 0, 0,
                    current_time.strftime('%Y-%m-%d %H:%M:%S'),
                    deadline.strftime('%Y-%m-%d %H:%M:%S'),
                    '', f"群組人數:{group_member_count}|價格詳情:{price_info}|{sell_data.get('note', '')}"
                ]
                voting_sheet.append_row(vote_data)
            except Exception as e:
                print(f"記錄投票到 Google Sheets 失敗: {e}")
        
        active_votes[vote_id] = {
            'initiator_id': user_id,
            'initiator_name': user_name,
            'group_id': group_id,
            'stock_code': sell_data['stock_code'],
            'stock_name': sell_data['stock_name'],
            'shares': sell_shares,
            'price': display_price,
            'price_details': sell_data.get('transactions', [{'shares': sell_shares, 'price': display_price}]),
            'deadline': deadline,
            'yes_votes': set(),
            'no_votes': set(),
            'voted_users': {},
            'status': 'active',
            'avg_cost': float(user_holding['平均成本']),
            'note': sell_data.get('note', ''),
            'group_member_count': group_member_count,
            'required_votes': 1 if group_member_count == 1 else max(2, group_member_count // 2 + 1)  # 私訊時只需1票
        }
        
        avg_cost = float(user_holding['平均成本'])
        expected_profit = (display_price - avg_cost) * sell_shares
        profit_percentage = ((display_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
        
        response = f"""📊 賣出投票已發起！

🎯 投票ID：{vote_id}
👤 發起人：{user_name}
🏢 股票：{sell_data['stock_name']} ({sell_data['stock_code']})
📉 賣出數量：{format_shares(sell_shares)}"""
        
        if sell_data.get('is_batch') and len(sell_data.get('transactions', [])) > 1:
            response += f"\n💰 賣出價格（批次）："
            for trans in sell_data['transactions']:
                response += f"\n  • {format_shares(trans['shares'])} @ {trans['price']:.2f}元"
            response += f"\n  • 平均價：{display_price:.2f}元"
        else:
            response += f"\n💰 賣出價格：{display_price:.2f}元"
        
        response += f"""
📈 平均成本：{avg_cost:.2f}元
💵 預期損益：{expected_profit:+,.0f}元 ({profit_percentage:+.2f}%)
⏰ 投票截止：{deadline.strftime('%m/%d %H:%M')}

👥 群組資訊："""
        
        # 根據情況顯示不同資訊
        if group_member_count == 1:
            response += f"\n• 私訊模式：您自己決定即可"
            response += f"\n• 通過門檻：1票（您自己）"
        else:
            response += f"\n• 群組成員：{group_member_count}人（不含機器人）"
            response += f"\n• 通過門檻：{active_votes[vote_id]['required_votes']}票（過半數）"
        
        response += f"""

📝 投票方式：
• 贊成請輸入：/贊成 {vote_id}
• 反對請輸入：/反對 {vote_id}
• 查看狀態：/投票狀態 {vote_id}"""
        
        if sell_data.get('note'):
            response += f"\n\n💭 備註：{sell_data['note']}"
        
        return response
        
    except Exception as e:
        print(f"創建投票錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return f"❌ 創建投票時發生錯誤: {str(e)[:200]}"

def get_group_member_count(group_id, user_id):
    """取得群組成員數量（排除機器人自己）"""
    try:
        # 私訊情況：只有使用者一人（不算機器人）
        if group_id == user_id:
            return 1  # 只有發起人自己
        
        if LINE_CHANNEL_ACCESS_TOKEN:
            from linebot import LineBotApi
            from linebot.exceptions import LineBotApiError
            
            line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
            
            try:
                group_member_count = line_bot_api.get_group_members_count(group_id)
                # 減去機器人自己，只計算真人數量
                human_count = group_member_count.count - 1
                return max(1, human_count)  # 至少要有1人（發起人）
            except LineBotApiError as e:
                print(f"無法取得群組成員數: {e}")
                # 預設假設有4個真人（不含機器人）
                return 4
        
        # 無法取得時，預設4個真人
        return 4
        
    except Exception as e:
        print(f"取得群組成員數錯誤: {e}")
        return 4

def handle_vote(user_id, user_name, group_id, vote_id, vote_type):
    """處理投票"""
    try:
        if vote_id not in active_votes:
            return f"❌ 找不到投票ID：{vote_id}"
        
        vote = active_votes[vote_id]
        
        if vote['status'] != 'active':
            return f"❌ 此投票已結束（狀態：{vote['status']}）"
        
        if datetime.now() > vote['deadline']:
            vote['status'] = 'expired'
            return "❌ 此投票已過期"
        
        if group_id != vote['group_id']:
            return "❌ 您不在此投票的群組中"
        
        old_vote = vote['voted_users'].get(user_id)
        
        if vote_type == 'yes':
            vote['no_votes'].discard(user_id)
            vote['yes_votes'].add(user_id)
            vote['voted_users'][user_id] = 'yes'
            action = "贊成"
        else:
            vote['yes_votes'].discard(user_id)
            vote['no_votes'].add(user_id)
            vote['voted_users'][user_id] = 'no'
            action = "反對"
        
        yes_count = len(vote['yes_votes'])
        no_count = len(vote['no_votes'])
        total_votes = yes_count + no_count
        required = vote['required_votes']
        
        response = f"""✅ 您已投下「{action}」票！"""
        
        if old_vote and old_vote != vote_type:
            response += f"（改票：{'反對→贊成' if vote_type == 'yes' else '贊成→反對'}）"
        
        response += f"""

📊 目前投票狀況：
• 贊成：{yes_count}票
• 反對：{no_count}票
• 總投票：{total_votes}票
• 通過門檻：{required}票"""
        
        if yes_count >= required:
            result = execute_sell(vote, vote_id)
            response += f"\n\n✅ 投票通過！\n{result}"
        elif no_count >= required:
            vote['status'] = 'rejected'
            response += "\n\n❌ 投票已否決，不執行賣出"
        else:
            need_yes = required - yes_count
            need_no = required - no_count
            response += f"\n\n📈 進度："
            if need_yes > 0:
                response += f"\n• 還需 {need_yes} 張贊成票可通過"
            if need_no > 0:
                response += f"\n• 還需 {need_no} 張反對票可否決"
        
        return response
        
    except Exception as e:
        print(f"處理投票錯誤: {e}")
        return f"❌ 處理投票時發生錯誤: {str(e)}"

def execute_sell(vote, vote_id):
    """執行賣出交易"""
    try:
        vote['status'] = 'executed'
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        total_amount = vote['shares'] * vote['price']
        total_profit = (vote['price'] - vote['avg_cost']) * vote['shares']
        record_id = str(int(datetime.now().timestamp()))
        
        # 記錄到交易紀錄
        if transaction_sheet:
            try:
                row_data = [
                    current_time, 
                    str(vote['initiator_id']), 
                    str(vote['initiator_name']),
                    str(vote['stock_code']), 
                    str(vote['stock_name']), 
                    '賣出',
                    int(vote['shares']), 
                    float(vote['price']), 
                    float(total_amount),
                    f"投票通過 (贊成:{len(vote['yes_votes'])} 反對:{len(vote['no_votes'])})",
                    str(vote['group_id']), 
                    str(record_id), 
                    str(vote_id), 
                    '已執行',
                    f"實現損益: {total_profit:+,.0f}元"
                ]
                transaction_sheet.append_row(row_data)
                print(f"✅ 賣出交易已記錄到交易紀錄表")
            except Exception as e:
                print(f"⚠️ 記錄賣出交易失敗: {e}")
        
        # 更新持股 - 這裡是關鍵！
        update_result = update_holdings(
            vote['initiator_id'], 
            vote['initiator_name'], 
            vote['group_id'],
            vote['stock_code'], 
            vote['stock_name'], 
            vote['shares'],
            vote['price'], 
            'sell'
        )
        
        if update_result:
            print(f"✅ 持股已更新：賣出 {vote['stock_name']} {vote['shares']} 股")
        else:
            print(f"❌ 持股更新失敗")
        
        return f"""🎉 賣出交易已執行！

📉 賣出：{vote['stock_name']} {format_shares(vote['shares'])}
💰 成交價：{vote['price']:.2f}元
💵 成交金額：{total_amount:,.0f}元
📊 實現損益：{total_profit:+,.0f}元

✅ 交易已記錄至 Google Sheets
✅ 持股已更新"""
        
    except Exception as e:
        print(f"執行賣出錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return f"❌ 執行賣出時發生錯誤: {str(e)}"

def get_vote_status(vote_id):
    """查詢投票狀態"""
    try:
        if vote_id not in active_votes:
            return f"❌ 找不到投票ID：{vote_id}"
        
        vote = active_votes[vote_id]
        
        time_left = vote['deadline'] - datetime.now()
        hours_left = int(time_left.total_seconds() / 3600)
        minutes_left = int((time_left.total_seconds() % 3600) / 60)
        
        status_text = f"""📊 投票狀態查詢

🎯 投票ID：{vote_id}
👤 發起人：{vote['initiator_name']}
🏢 股票：{vote['stock_name']} ({vote['stock_code']})
📉 賣出數量：{format_shares(vote['shares'])}
💰 賣出價格：{vote['price']:.2f}元

📈 投票進度：
• 贊成：{len(vote['yes_votes'])}票
• 反對：{len(vote['no_votes'])}票
• 狀態：{vote['status']}"""
        
        if vote['status'] == 'active':
            if hours_left > 0:
                status_text += f"\n⏰ 剩餘時間：{hours_left}小時{minutes_left}分鐘"
            else:
                status_text += f"\n⏰ 剩餘時間：{minutes_left}分鐘"
        
        return status_text
        
    except Exception as e:
        print(f"查詢投票狀態錯誤: {e}")
        return f"❌ 查詢投票狀態時發生錯誤: {str(e)}"

def list_active_votes(group_id):
    """列出群組中所有進行中的投票"""
    try:
        group_votes = []
        
        for vote_id, vote in active_votes.items():
            if vote['group_id'] == group_id and vote['status'] == 'active':
                if vote['deadline'] > datetime.now():
                    time_left = vote['deadline'] - datetime.now()
                    hours_left = int(time_left.total_seconds() / 3600)
                    
                    group_votes.append({
                        'id': vote_id,
                        'stock': vote['stock_name'],
                        'shares': format_shares(vote['shares']),
                        'price': vote['price'],
                        'yes': len(vote['yes_votes']),
                        'no': len(vote['no_votes']),
                        'hours_left': hours_left
                    })
        
        if not group_votes:
            return "📊 目前沒有進行中的投票"
        
        response = "📊 進行中的投票：\n\n"
        for vote in group_votes:
            response += f"""🎯 ID: {vote['id']}
• {vote['stock']} {vote['shares']} @ {vote['price']:.2f}元
• 贊成:{vote['yes']} 反對:{vote['no']}
• 剩餘:{vote['hours_left']}小時
{'='*20}\n"""
        
        response += "\n💡 投票指令：/贊成 [ID] 或 /反對 [ID]"
        
        return response
        
    except Exception as e:
        print(f"列出投票錯誤: {e}")
        return f"❌ 列出投票時發生錯誤: {str(e)}"

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
    
    if len(message_text) > 5000:
        message_text = message_text[:4997] + "..."
    
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
        "message": "🤖 完整版股票管理 LINE Bot v3.5",
        "version": "3.5",
        "timestamp": datetime.now().isoformat(),
        "features": [
            "買入股票（支援批次）",
            "賣出投票（支援批次）",
            "持股查詢（支援查看他人）",
            "投票系統",
            "即時股價（動態爬取）",
            "零股支援",
            "查看他人持股功能",
            "動態股票清單"
        ],
        "sheets_connected": bool(transaction_sheet and holdings_sheet),
        "environment_vars": {
            "LINE_CHANNEL_ACCESS_TOKEN": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "LINE_CHANNEL_SECRET": bool(LINE_CHANNEL_SECRET),
            "SPREADSHEET_ID": bool(SPREADSHEET_ID),
            "GOOGLE_CREDENTIALS": bool(GOOGLE_CREDENTIALS_JSON)
        },
        "stock_codes_count": len(STOCK_CODES)
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
                user_name = "未知使用者"
                try:
                    from linebot import LineBotApi
                    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
                    if group_id != user_id:
                        profile = line_bot_api.get_group_member_profile(group_id, user_id)
                    else:
                        profile = line_bot_api.get_profile(user_id)
                    user_name = profile.display_name
                except Exception as e:
                    print(f"無法取得使用者名稱: {e}")
                
                print(f"💬 收到訊息: '{message_text}' 來自: {user_name}")
                
                response_text = None
                
                # === 處理各種指令 ===
                
                # 買入指令
                if message_text.startswith('/買入'):
                    buy_data = parse_buy_command(message_text)
                    if buy_data:
                        response_text = handle_buy_stock(user_id, user_name, group_id, buy_data)
                    else:
                        response_text = """❌ 買入指令格式錯誤

✅ 支援的格式：

【單筆買入】
/買入 台積電 5張 580元 看好AI趨勢
/買入 2330 500股 580元 技術突破

【批次買入】
/買入 台積電 2張 580元 3張 575元 看好AI趨勢
/買入 2330 1 580元 2 575元 逢低布局

💡 提示：
• 數量可用「張」或「股」
• 只寫數字時，小於1000視為張數"""

                # 賣出指令
                elif message_text.startswith('/賣出'):
                    sell_data = parse_sell_command(message_text)
                    if sell_data:
                        response_text = create_sell_voting(user_id, user_name, group_id, sell_data)
                    else:
                        response_text = """❌ 賣出指令格式錯誤

✅ 支援的格式：

【單筆賣出】
/賣出 台積電 2張 600元
/賣出 2330 500股 1150元 停損

【批次賣出】
/賣出 台積電 1張 600元 2張 605元
/賣出 2330 1 600元 2 605元 分批獲利"""

                # 持股查詢（支援查看他人）
                elif message_text.startswith('/持股'):
                    parts = message_text.split()
                    if len(parts) == 1:
                        response_text = get_user_holdings(user_id, group_id)
                    elif len(parts) >= 2:
                        query = ' '.join(parts[1:])  # 支援多字名稱
                        response_text = get_user_holdings(user_id, group_id, query)
                    else:
                        response_text = """❌ 持股查詢格式錯誤

✅ 支援的格式：
• /持股 - 查看自己的所有持股
• /持股 台積電 - 查看自己特定股票
• /持股 張三 - 查看張三的持股
• /持股 全部 - 查看群組所有人的持股"""

                # 股價查詢
                elif message_text.startswith('/股價'):
                    parts = message_text.split()
                    if len(parts) >= 2:
                        stock_input = ' '.join(parts[1:])  # 支援多字股票名稱
                        print(f"查詢股價: {stock_input}")
                        
                        # 特殊處理：如果輸入是純數字，當作股票代號
                        if stock_input.isdigit() and len(stock_input) == 4:
                            stock_code = stock_input
                            stock_name = stock_input  # 暫時用代號當名稱
                            print(f"直接使用股票代號: {stock_code}")
                        else:
                            # 取得股票代號
                            stock_code, stock_name = get_stock_code(stock_input)
                            print(f"查詢結果 - 代號: {stock_code}, 名稱: {stock_name}")
                        
                        # 嘗試取得股價
                        if stock_code or stock_input.isdigit():
                            # 如果有代號，或輸入是數字，嘗試查詢
                            query_code = stock_code if stock_code else stock_input
                            price = get_stock_price(query_code, stock_name)
                            
                            if price > 0:
                                # 成功取得股價
                                display_name = stock_name if stock_name != query_code else f"股票 {query_code}"
                                response_text = f"""📊 股價查詢結果

🏢 股票：{display_name} ({query_code})
💰 目前股價：{price:.2f}元
⏰ 查詢時間：{datetime.now().strftime('%H:%M:%S')}"""
                                
                                # 如果原本沒有這支股票，加入快取
                                if query_code not in STOCK_CODES:
                                    STOCK_CODES[query_code] = stock_name
                                    STOCK_NAMES[stock_name] = query_code
                                    print(f"新增股票到快取: {query_code} {stock_name}")
                            else:
                                # 無法取得股價
                                response_text = f"""❌ 無法取得股價：{stock_input}

可能原因：
1. 股票代號或名稱錯誤
2. 股市休市中
3. 網路連線問題

請確認：
• 上市股票代號（如：2330）
• 上櫃股票代號（如：3078）
• 正確的股票名稱"""
                        else:
                            # 完全找不到股票
                            response_text = f"""❌ 找不到股票：{stock_input}

請使用：
• 4位數股票代號（如：2330）
• 完整股票名稱（如：台積電）

💡 提示：
• 上市股票：2330（台積電）、2317（鴻海）
• 上櫃股票：3078（波若威）、6547（高端疫苗）"""
                    else:
                        response_text = "❌ 請輸入要查詢的股票\n\n格式：/股價 股票名稱\n範例：/股價 台積電 或 /股價 2330"

                # 投票相關
                elif message_text.startswith('/贊成'):
                    parts = message_text.split()
                    if len(parts) == 2:
                        vote_id = parts[1]
                        response_text = handle_vote(user_id, user_name, group_id, vote_id, 'yes')
                    else:
                        response_text = "❌ 格式錯誤\n正確格式：/贊成 投票ID"

                elif message_text.startswith('/反對'):
                    parts = message_text.split()
                    if len(parts) == 2:
                        vote_id = parts[1]
                        response_text = handle_vote(user_id, user_name, group_id, vote_id, 'no')
                    else:
                        response_text = "❌ 格式錯誤\n正確格式：/反對 投票ID"

                elif message_text.startswith('/投票狀態'):
                    parts = message_text.split()
                    if len(parts) == 2:
                        vote_id = parts[1]
                        response_text = get_vote_status(vote_id)
                    else:
                        response_text = "❌ 格式錯誤\n正確格式：/投票狀態 投票ID"

                elif message_text == '/投票' or message_text == '/投票清單':
                    response_text = list_active_votes(group_id)

                # 股票清單
                elif message_text == '/股票清單':
                    if not STOCK_CODES:
                        init_stock_list()
                    
                    stock_list = f"📋 支援的股票清單（共 {len(STOCK_CODES)} 支）：\n\n"
                    count = 0
                    for code, name in sorted(STOCK_CODES.items())[:50]:  # 只顯示前50支
                        stock_list += f"• {code} - {name}\n"
                        count += 1
                    
                    if len(STOCK_CODES) > 50:
                        stock_list += f"\n... 還有 {len(STOCK_CODES) - 50} 支股票\n"
                        stock_list += "\n💡 系統支援所有上市櫃股票，可直接輸入代號或名稱查詢"
                    
                    response_text = stock_list

                # 幫助
                elif message_text == '/幫助' or message_text == '/help':
                    response_text = """📚 股票管理機器人使用說明

💰 交易指令：
• /買入 股票 數量 價格 理由
• /賣出 股票 數量 價格 [備註]

📊 查詢指令：
• /持股 - 查看自己的所有持股
• /持股 股票名稱 - 查看自己特定股票
• /持股 用戶名稱 - 查看他人持股 🆕
• /持股 全部 - 查看群組所有人持股 🆕
• /股價 股票名稱 - 查詢即時股價

🗳️ 投票指令：
• /贊成 投票ID - 投贊成票
• /反對 投票ID - 投反對票
• /投票狀態 投票ID - 查詢狀態
• /投票 - 列出進行中投票

ℹ️ 其他指令：
• /股票清單 - 支援的股票
• /測試 - 系統診斷
• /幫助 - 顯示此說明

💡 批次交易範例：
• /買入 台積電 2 580元 3 575元 加碼
• /賣出 2330 1 600元 2 605元

🆕 查看他人持股範例：
• /持股 王小明 - 查看王小明的持股
• /持股 全部 - 查看群組所有人的持股總覽

📌 系統支援所有上市櫃股票（動態更新）"""

                # 測試
                elif message_text == '/測試':
                    test_results = "🤖 系統測試報告：\n\n"
                    test_results += f"✅ Webhook 連接成功\n"
                    test_results += f"✅ Google Sheets: {'已連接' if holdings_sheet else '未連接'}\n"
                    test_results += f"✅ LINE Token: {'已設置' if LINE_CHANNEL_ACCESS_TOKEN else '未設置'}\n"
                    test_results += f"✅ 股票清單: {len(STOCK_CODES)} 支股票\n"
                    test_results += f"\n📊 股價測試（台積電 2330）：\n"
                    
                    test_price = get_stock_price('2330', '台積電')
                    if test_price > 0:
                        test_results += f"✅ 股價抓取成功：{test_price}元\n"
                    else:
                        test_results += f"❌ 股價抓取失敗\n"
                    
                    test_results += f"\n🌐 運行環境：Vercel\n"
                    test_results += f"⏰ 系統時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    test_results += f"📦 版本：3.5 (動態股票清單)"
                    
                    response_text = test_results

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
