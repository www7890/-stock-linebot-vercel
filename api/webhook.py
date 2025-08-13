# 在原有的程式碼中加入以下賣出相關功能

import uuid
from datetime import datetime, timedelta

# 儲存進行中的投票（在實際部署時應該存在資料庫或 Redis）
active_votes = {}

def create_sell_voting(user_id, user_name, group_id, sell_data):
    """創建賣出投票"""
    try:
        # 檢查使用者是否有足夠的持股
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
        if current_shares < sell_data['shares']:
            return f"❌ 持股不足！\n您只有 {format_shares(current_shares)}，無法賣出 {format_shares(sell_data['shares'])}"
        
        # 創建投票ID
        vote_id = str(uuid.uuid4())[:8]
        current_time = datetime.now()
        deadline = current_time + timedelta(hours=24)  # 24小時投票期限
        
        # 記錄到投票表
        if voting_sheet:
            vote_data = [
                vote_id,
                user_id,
                user_name,
                sell_data['stock_code'],
                sell_data['stock_name'],
                sell_data['shares'],
                sell_data['price'],
                group_id,
                '進行中',  # 投票狀態
                0,  # 贊成票數
                0,  # 反對票數
                current_time.strftime('%Y-%m-%d %H:%M:%S'),
                deadline.strftime('%Y-%m-%d %H:%M:%S'),
                '',  # 結果
                sell_data.get('note', '')  # 備註
            ]
            voting_sheet.append_row(vote_data)
        
        # 儲存投票資訊到記憶體（實際應用應該用資料庫）
        active_votes[vote_id] = {
            'initiator_id': user_id,
            'initiator_name': user_name,
            'group_id': group_id,
            'stock_code': sell_data['stock_code'],
            'stock_name': sell_data['stock_name'],
            'shares': sell_data['shares'],
            'price': sell_data['price'],
            'deadline': deadline,
            'yes_votes': set(),
            'no_votes': set(),
            'status': 'active',
            'avg_cost': float(user_holding['平均成本']),
            'note': sell_data.get('note', '')
        }
        
        # 計算預期損益
        avg_cost = float(user_holding['平均成本'])
        expected_profit = (sell_data['price'] - avg_cost) * sell_data['shares']
        profit_percentage = ((sell_data['price'] - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
        
        # 產生回應訊息
        response = f"""📊 賣出投票已發起！

🎯 投票ID：{vote_id}
👤 發起人：{user_name}
🏢 股票：{sell_data['stock_name']} ({sell_data['stock_code']})
📉 賣出數量：{format_shares(sell_data['shares'])}
💰 賣出價格：{sell_data['price']:.2f}元
📈 平均成本：{avg_cost:.2f}元
💵 預期損益：{expected_profit:+,.0f}元 ({profit_percentage:+.2f}%)
⏰ 投票截止：{deadline.strftime('%Y-%m-%d %H:%M')}

📝 投票方式：
• 贊成請輸入：/贊成 {vote_id}
• 反對請輸入：/反對 {vote_id}
• 查看狀態：/投票狀態 {vote_id}

⚠️ 需要超過半數群組成員贊成才能執行賣出"""
        
        if sell_data.get('note'):
            response += f"\n\n💭 備註：{sell_data['note']}"
        
        return response
        
    except Exception as e:
        print(f"❌ 創建投票錯誤: {e}")
        return f"❌ 創建賣出投票時發生錯誤: {str(e)}"

def handle_vote(user_id, user_name, group_id, vote_id, vote_type):
    """處理投票（贊成/反對）"""
    try:
        # 從記憶體查找投票（實際應用應該從資料庫查詢）
        if vote_id not in active_votes:
            # 嘗試從 Google Sheets 恢復投票資訊
            if not restore_vote_from_sheet(vote_id):
                return f"❌ 找不到投票ID：{vote_id}"
        
        vote = active_votes[vote_id]
        
        # 檢查投票是否已結束
        if vote['status'] != 'active':
            return f"❌ 此投票已結束（狀態：{vote['status']}）"
        
        # 檢查是否超過期限
        if datetime.now() > vote['deadline']:
            vote['status'] = 'expired'
            update_vote_status(vote_id, '已過期')
            return "❌ 此投票已過期"
        
        # 檢查是否為同一群組
        if group_id != vote['group_id']:
            return "❌ 您不在此投票的群組中"
        
        # 處理投票
        if vote_type == 'yes':
            # 從反對票中移除（如果有）
            vote['no_votes'].discard(user_id)
            # 加入贊成票
            vote['yes_votes'].add(user_id)
            action = "贊成"
        else:
            # 從贊成票中移除（如果有）
            vote['yes_votes'].discard(user_id)
            # 加入反對票
            vote['no_votes'].add(user_id)
            action = "反對"
        
        # 更新 Google Sheets
        update_vote_count(vote_id, len(vote['yes_votes']), len(vote['no_votes']))
        
        # 檢查是否需要執行賣出（簡單多數決）
        total_votes = len(vote['yes_votes']) + len(vote['no_votes'])
        
        response = f"""✅ 您已投下「{action}」票！

📊 目前投票狀況：
• 贊成：{len(vote['yes_votes'])}票
• 反對：{len(vote['no_votes'])}票
• 總票數：{total_votes}票"""
        
        # 檢查是否達到執行條件（這裡設定為至少3人投票且贊成過半）
        if total_votes >= 3 and len(vote['yes_votes']) > len(vote['no_votes']):
            # 執行賣出
            result = execute_sell(vote)
            response += f"\n\n{result}"
        elif total_votes >= 5 and len(vote['no_votes']) > len(vote['yes_votes']):
            # 否決
            vote['status'] = 'rejected'
            update_vote_status(vote_id, '已否決')
            response += "\n\n❌ 投票已否決，不執行賣出"
        
        return response
        
    except Exception as e:
        print(f"❌ 處理投票錯誤: {e}")
        return f"❌ 處理投票時發生錯誤: {str(e)}"

def execute_sell(vote):
    """執行賣出交易"""
    try:
        # 標記投票為已執行
        vote['status'] = 'executed'
        vote_id = None
        for vid, v in active_votes.items():
            if v == vote:
                vote_id = vid
                break
        
        # 記錄賣出交易
        total_amount = vote['shares'] * vote['price']
        profit = (vote['price'] - vote['avg_cost']) * vote['shares']
        record_id = str(int(datetime.now().timestamp()))
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 記錄到交易紀錄
        if transaction_sheet:
            row_data = [
                current_time,
                vote['initiator_id'],
                vote['initiator_name'],
                vote['stock_code'],
                vote['stock_name'],
                '賣出',
                vote['shares'],
                vote['price'],
                total_amount,
                f"投票通過 (贊成:{len(vote['yes_votes'])} 反對:{len(vote['no_votes'])})",
                vote['group_id'],
                record_id,
                vote_id,
                '已執行',
                f"實現損益: {profit:+,.0f}元"
            ]
            transaction_sheet.append_row(row_data)
        
        # 更新持股統計
        update_holdings(
            vote['initiator_id'],
            vote['initiator_name'],
            vote['group_id'],
            vote['stock_code'],
            vote['stock_name'],
            vote['shares'],
            vote['price'],
            'sell'
        )
        
        # 更新投票狀態
        if vote_id:
            update_vote_status(vote_id, '已執行')
        
        return f"""🎉 賣出交易已執行！

📉 賣出：{vote['stock_name']} {format_shares(vote['shares'])}
💰 成交價：{vote['price']:.2f}元
💵 成交金額：{total_amount:,.0f}元
📊 實現損益：{profit:+,.0f}元

✅ 交易已記錄至 Google Sheets"""
        
    except Exception as e:
        print(f"❌ 執行賣出錯誤: {e}")
        return f"❌ 執行賣出時發生錯誤: {str(e)}"

def get_vote_status(vote_id):
    """查詢投票狀態"""
    try:
        # 從記憶體查找
        if vote_id not in active_votes:
            # 嘗試從 Google Sheets 恢復
            if not restore_vote_from_sheet(vote_id):
                return f"❌ 找不到投票ID：{vote_id}"
        
        vote = active_votes[vote_id]
        
        # 計算時間
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
        print(f"❌ 查詢投票狀態錯誤: {e}")
        return f"❌ 查詢投票狀態時發生錯誤: {str(e)}"

def restore_vote_from_sheet(vote_id):
    """從 Google Sheets 恢復投票資訊"""
    try:
        if not voting_sheet:
            return False
        
        records = voting_sheet.get_all_records()
        for record in records:
            if record['投票ID'] == vote_id and record['投票狀態'] == '進行中':
                deadline = datetime.strptime(record['截止時間'], '%Y-%m-%d %H:%M:%S')
                
                # 恢復到記憶體
                active_votes[vote_id] = {
                    'initiator_id': record['發起人ID'],
                    'initiator_name': record['發起人名稱'],
                    'group_id': record['群組ID'],
                    'stock_code': record['股票代號'],
                    'stock_name': record['股票名稱'],
                    'shares': int(record['賣出股數']),
                    'price': float(record['賣出價格']),
                    'deadline': deadline,
                    'yes_votes': set(),  # 這裡無法恢復投票者，需要另外儲存
                    'no_votes': set(),
                    'status': 'active',
                    'avg_cost': 0,  # 需要從持股表查詢
                    'note': record.get('備註', '')
                }
                return True
        
        return False
        
    except Exception as e:
        print(f"恢復投票資訊錯誤: {e}")
        return False

def update_vote_count(vote_id, yes_count, no_count):
    """更新 Google Sheets 中的投票數"""
    try:
        if not voting_sheet:
            return
        
        records = voting_sheet.get_all_records()
        for i, record in enumerate(records, 2):
            if record['投票ID'] == vote_id:
                voting_sheet.update(f'J{i}:K{i}', [[yes_count, no_count]])
                break
                
    except Exception as e:
        print(f"更新投票數錯誤: {e}")

def update_vote_status(vote_id, status):
    """更新投票狀態"""
    try:
        if not voting_sheet:
            return
        
        records = voting_sheet.get_all_records()
        for i, record in enumerate(records, 2):
            if record['投票ID'] == vote_id:
                voting_sheet.update(f'I{i}', status)
                if status in ['已執行', '已否決', '已過期']:
                    voting_sheet.update(f'N{i}', status)
                break
                
    except Exception as e:
        print(f"更新投票狀態錯誤: {e}")

def list_active_votes(group_id):
    """列出群組中所有進行中的投票"""
    try:
        if not voting_sheet:
            return "❌ 無法連接投票資料庫"
        
        records = voting_sheet.get_all_records()
        active_list = []
        
        for record in records:
            if record['群組ID'] == group_id and record['投票狀態'] == '進行中':
                deadline = datetime.strptime(record['截止時間'], '%Y-%m-%d %H:%M:%S')
                if deadline > datetime.now():
                    active_list.append({
                        'id': record['投票ID'],
                        'stock': record['股票名稱'],
                        'shares': format_shares(int(record['賣出股數'])),
                        'price': float(record['賣出價格']),
                        'yes': int(record['贊成票數'] or 0),
                        'no': int(record['反對票數'] or 0),
                        'deadline': deadline
                    })
        
        if not active_list:
            return "📊 目前沒有進行中的投票"
        
        response = "📊 進行中的投票：\n\n"
        for vote in active_list:
            time_left = vote['deadline'] - datetime.now()
            hours_left = int(time_left.total_seconds() / 3600)
            
            response += f"""🎯 ID: {vote['id']}
• {vote['stock']} {vote['shares']} @ {vote['price']:.2f}元
• 贊成:{vote['yes']} 反對:{vote['no']}
• 剩餘:{hours_left}小時
{'='*20}\n"""
        
        response += "\n💡 投票指令：/贊成 [ID] 或 /反對 [ID]"
        
        return response
        
    except Exception as e:
        print(f"列出投票錯誤: {e}")
        return f"❌ 列出投票時發生錯誤: {str(e)}"

# 在 webhook 函數中加入以下處理邏輯：

def handle_sell_command(message_text, user_id, user_name, group_id):
    """處理賣出相關指令"""
    
    # 賣出投票
    if message_text.startswith('/賣出'):
        sell_data = parse_sell_command(message_text)
        if sell_data:
            return create_sell_voting(user_id, user_name, group_id, sell_data)
        else:
            return """❌ 賣出指令格式錯誤

正確格式：/賣出 股票名稱 數量 價格 [備註]

範例：
• /賣出 台積電 2張 600元
• /賣出 2330 1000股 600元 獲利了結
• /賣出 聯發科 3張 1300元 達到目標價"""
    
    # 贊成投票
    elif message_text.startswith('/贊成'):
        parts = message_text.split()
        if len(parts) == 2:
            vote_id = parts[1]
            return handle_vote(user_id, user_name, group_id, vote_id, 'yes')
        else:
            return "❌ 格式錯誤\n正確格式：/贊成 投票ID"
    
    # 反對投票
    elif message_text.startswith('/反對'):
        parts = message_text.split()
        if len(parts) == 2:
            vote_id = parts[1]
            return handle_vote(user_id, user_name, group_id, vote_id, 'no')
        else:
            return "❌ 格式錯誤\n正確格式：/反對 投票ID"
    
    # 查詢投票狀態
    elif message_text.startswith('/投票狀態'):
        parts = message_text.split()
        if len(parts) == 2:
            vote_id = parts[1]
            return get_vote_status(vote_id)
        else:
            return "❌ 格式錯誤\n正確格式：/投票狀態 投票ID"
    
    # 列出所有投票
    elif message_text == '/投票' or message_text == '/投票清單':
        return list_active_votes(group_id)
    
    return None
