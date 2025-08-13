import re
import datetime
from datetime import datetime, timedelta

def parse_batch_buy_command(text):
    """
    解析批次買入指令，支援多個價格（簡化版，不需要@）
    格式: /買入 台積電 2張 580元 3張 575元 看好AI趨勢
    或: /買入 2330 1000股 580元 500股 575元 看好AI
    """
    try:
        # 移除開頭的 /買入
        text = text[3:].strip()
        
        # 分離股票名稱
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return None
        
        stock_input = parts[0]
        remaining = parts[1]
        
        # 新的解析模式：數量 價格 的配對
        # 匹配: 數字+張/股 數字+元
        pattern = r'(\d+(?:\.\d+)?)\s*(張|股)?\s+(\d+(?:\.\d+)?)\s*元'
        matches = re.findall(pattern, remaining)
        
        if not matches:
            # 如果沒有匹配到批次格式，嘗試單一價格格式
            # 格式: /買入 股票 數量 價格 理由
            single_pattern = r'^(.+?)\s+(\d+(?:\.\d+)?)\s*元\s+(.+)$'
            single_match = re.match(single_pattern, remaining)
            
            if single_match:
                shares_text = single_match.group(1).strip()
                price = float(single_match.group(2))
                reason = single_match.group(3).strip()
                
                shares = parse_shares(shares_text)
                if shares > 0:
                    stock_code, stock_name = get_stock_code(stock_input)
                    return {
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'shares': shares,
                        'price': price,
                        'reason': reason,
                        'is_batch': False
                    }
            return None
        
        # 找出理由（在最後一個價格之後的文字）
        last_match = matches[-1]
        # 構建最後一個匹配的完整字符串
        last_pattern = f"{last_match[0]}\\s*{last_match[1] if last_match[1] else ''}\\s+{last_match[2]}\\s*元"
        
        # 使用 re.search 找到最後一個匹配的位置
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
            
            # 判斷單位
            if unit == '股':
                shares = int(quantity)
            elif unit == '張':
                shares = int(quantity * 1000)
            else:
                # 沒有單位時的判斷邏輯
                if quantity >= 1000:
                    shares = int(quantity)  # 大於1000視為股數
                else:
                    shares = int(quantity * 1000)  # 小於1000視為張數
            
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
        
    except Exception as e:
        print(f"解析批次買入錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return None

def parse_batch_sell_command(text):
    """
    解析批次賣出指令，支援多個價格（簡化版，不需要@）
    格式: /賣出 台積電 2張 600元 3張 605元 獲利了結
    """
    try:
        text = text[3:].strip()
        parts = text.split(maxsplit=1)
        
        if len(parts) < 2:
            return None
        
        stock_input = parts[0]
        remaining = parts[1]
        
        # 匹配: 數字+張/股 數字+元
        pattern = r'(\d+(?:\.\d+)?)\s*(張|股)?\s+(\d+(?:\.\d+)?)\s*元'
        matches = re.findall(pattern, remaining)
        
        if not matches:
            # 單一價格格式
            single_pattern = r'^(.+?)\s+(\d+(?:\.\d+)?)\s*元(?:\s+(.+))?$'
            single_match = re.match(single_pattern, remaining)
            
            if single_match:
                shares_text = single_match.group(1).strip()
                price = float(single_match.group(2))
                note = single_match.group(3).strip() if single_match.group(3) else ''
                
                shares = parse_shares(shares_text)
                if shares > 0:
                    stock_code, stock_name = get_stock_code(stock_input)
                    return {
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'shares': shares,
                        'price': price,
                        'note': note,
                        'is_batch': False
                    }
            return None
        
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
            'note': note,
            'is_batch': True
        }
        
    except Exception as e:
        print(f"解析批次賣出錯誤: {e}")
        import traceback
        print(traceback.format_exc())
        return None

def handle_buy_command_unified(user_id, user_name, group_id, message_text):
    """統一處理買入指令（支援單筆和批次）"""
    buy_data = parse_batch_buy_command(message_text)
    
    if not buy_data:
        return """❌ 買入指令格式錯誤

✅ 支援的格式：

【單筆買入】
/買入 台積電 5張 580元 看好AI趨勢
/買入 2330 500股 580元 技術突破

【批次買入】
/買入 台積電 2張 580元 3張 575元 看好AI趨勢
/買入 2330 1000股 580元 500股 575元 逢低布局

💡 提示：
• 數量可用「張」或「股」
• 只寫數字時，小於1000視為張數
• 支援多個不同價格的買入"""
    
    # 根據是否為批次交易來處理
    if buy_data.get('is_batch') and len(buy_data.get('transactions', [])) > 1:
        return handle_batch_buy_stock(user_id, user_name, group_id, buy_data)
    else:
        # 單筆交易使用原有函數
        return handle_buy_stock(user_id, user_name, group_id, buy_data)

def handle_sell_command_unified(user_id, user_name, group_id, message_text):
    """統一處理賣出指令（支援單筆和批次）"""
    sell_data = parse_batch_sell_command(message_text)
    
    if not sell_data:
        return """❌ 賣出指令格式錯誤

✅ 支援的格式：

【單筆賣出】
/賣出 台積電 2張 600元
/賣出 2330 1000股 600元 獲利了結

【批次賣出】
/賣出 台積電 1張 600元 2張 605元
/賣出 2330 500股 600元 500股 605元 分批獲利

💡 提示：
• 賣出會發起群組投票
• 超過50%成員贊成即執行
• 投票有效期24小時"""
    
    # 創建賣出投票（支援批次價格）
    return create_sell_voting_with_member_count(user_id, user_name, group_id, sell_data)

# 測試函數
def test_parsing():
    """測試解析功能"""
    test_cases = [
        # 單筆買入
        "/買入 台積電 5張 580元 看好AI趨勢",
        "/買入 2330 500股 580元 技術突破",
        "/買入 台積電 5 580元 測試",
        
        # 批次買入
        "/買入 台積電 2張 580元 3張 575元 看好AI趨勢",
        "/買入 2330 1000股 580元 500股 575元 逢低布局",
        "/買入 聯發科 1 1200元 2 1195元 3 1190元 分批建倉",
        
        # 單筆賣出
        "/賣出 台積電 2張 600元",
        "/賣出 2330 1000股 600元 獲利了結",
        
        # 批次賣出
        "/賣出 台積電 1張 600元 2張 605元",
        "/賣出 2330 500股 600元 500股 605元 分批獲利",
        "/賣出 聯發科 1 1300元 1 1305元 1 1310元 逐步出場"
    ]
    
    print("=" * 50)
    print("測試買賣指令解析")
    print("=" * 50)
    
    for test in test_cases:
        print(f"\n測試: {test}")
        
        if test.startswith("/買入"):
            result = parse_batch_buy_command(test)
            if result:
                print(f"✅ 解析成功")
                print(f"  股票: {result['stock_name']} ({result['stock_code']})")
                if result.get('is_batch'):
                    print(f"  批次交易:")
                    for i, trans in enumerate(result['transactions'], 1):
                        print(f"    {i}. {format_shares(trans['shares'])} @ {trans['price']}元 = {trans['amount']:,.0f}元")
                    print(f"  平均價: {result['avg_price']:.2f}元")
                else:
                    print(f"  單筆: {format_shares(result['shares'])} @ {result['price']}元")
                print(f"  理由: {result.get('reason', '')}")
            else:
                print("❌ 解析失敗")
                
        elif test.startswith("/賣出"):
            result = parse_batch_sell_command(test)
            if result:
                print(f"✅ 解析成功")
                print(f"  股票: {result['stock_name']} ({result['stock_code']})")
                if result.get('is_batch'):
                    print(f"  批次交易:")
                    for i, trans in enumerate(result['transactions'], 1):
                        print(f"    {i}. {format_shares(trans['shares'])} @ {trans['price']}元 = {trans['amount']:,.0f}元")
                    print(f"  平均價: {result['avg_price']:.2f}元")
                else:
                    print(f"  單筆: {format_shares(result['shares'])} @ {result['price']}元")
                print(f"  備註: {result.get('note', '')}")
            else:
                print("❌ 解析失敗")

# 輔助函數（需要從主程式引入）
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

def get_stock_code(input_text):
    """取得股票代號（示例函數，實際需要從主程式引入）"""
    # 這裡需要實際的股票代號對應表
    STOCK_CODES = {
        '2330': '台積電',
        '2454': '聯發科',
        '2317': '鴻海',
    }
    STOCK_NAMES = {v: k for k, v in STOCK_CODES.items()}
    
    input_text = input_text.strip()
    
    if input_text in STOCK_CODES:
        return input_text, STOCK_CODES[input_text]
    
    if input_text in STOCK_NAMES:
        return STOCK_NAMES[input_text], input_text
    
    return '', input_text

# 如果直接執行此檔案，運行測試
if __name__ == "__main__":
    test_parsing()
