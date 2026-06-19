def initialize(context):
    #用户可修改参数
    g.sec_list =["600651.SS", "002123.SZ", "300214.SZ", "300683.SZ", "600881.SS", 
                 "002526.SZ", "300865.SZ", "300629.SZ", "688656.SS", "301141.SZ",
                 "300975.SZ", "603208.SS", "600543.SS", "603960.SS", "688620.SS",
                 "301633.SZ", "300438.SZ", "301571.SZ", "300418.SZ", "300290.SZ",
                 "300210.SZ", "300121.SZ"
                ]
    g.config = {
        'event_time': '9:30',     # 触发时间  可设置范围是 09:30--11:29, 13:00--14:59
        'n1': 6,                  # 买入参数
        'n2': 12,                  # 卖出参数
        'ATR':10,                 # ATR参数
        '减仓ATR':0.03,           # 减仓时，每单位atr的变动减仓多少百分比的资金
        '加仓ATR':0.02,           # 加仓时，每单位atr的变动增加多少百分比的资金
        '入场ATR':0.02,           # 入场时，每单位atr的变动买入多少百分比的资金
        'SL':-0.05,              # 止损
        'ydSL':0.08,              # 移动止损
        'TP':0.20,                # 止盈  
        'buy_amount':30000,        #单次买入金额上限
        'sec_max':5,                #最大持仓股票数量
        'max_position_amount':50000, #单只买入限额
        'buy_field':1.01        #买入限价比例,涨幅不超过1%才买入  
    }
    run_daily(context, daily_event, time=g.config['event_time'])  #设置触发时间


def before_trading_start(context, data):
    log.info('')
    log.info('日级别海龟策略')
    # for sec, buy_amount in g.sec_dict.items():
        # log.info('{}:买入金额{}'.format(sec, buy_amount))
    log.info('触发时间: {}'.format(g.config['event_time']))
    log.info('策略正常运行 {}'.format(context.blotter.current_dt))


def daily_event(context):
    today_sell=[]
    for sec in g.sec_list:  #先清仓，再处理其他，便于控制仓位
        sec_his = get_history(count=60, frequency='1d', field=['close','low','high'], security_list=sec, fq='pre', include=False)
        sec_his['up'] = sec_his['high'].shift(1).rolling(window=g.config['n1']).max()   #上线
        sec_his['down'] = sec_his['low'].shift(1).rolling(window=g.config['n2']).min()   #下线
        
        high, low, close = sec_his['high'], sec_his['low'], sec_his['close']
        trueHigh = high.where(high>(close.shift(1)), (close.shift(1)))
        trueLow = low.where(low<(close.shift(1)), (close.shift(1)))
        atr = (trueHigh - trueLow)[-g.config['ATR']:].mean()
        stop_loss_price = sec_his['up'][-1] *(1-g.config['ydSL'])          #移动止损价格  
        
        posInfo = get_position(sec)
        price = posInfo.last_sale_price
        
        holdRet = posInfo.last_sale_price/posInfo.cost_basis-1 if posInfo.cost_basis!=0 else 0
        if posInfo.enable_amount>0:
            #清仓:持有股票时监控昨日最低价是否低于下线，低于下线卖出。增加止盈止损，涨停不卖
            if sec_his['low'][-1] < sec_his['down'][-1] or holdRet <= g.config['SL'] or holdRet >= g.config['TP']  or posInfo.last_sale_price <= stop_loss_price and check_limit(sec)!=1:
                vol = posInfo.enable_amount
                if vol >0:
                    order(sec, -vol)
                    log.info('清仓')
                    today_sell.append(sec)

    log.info('今日清仓:{}'.format(today_sell))
    for sec in g.sec_list:
        sec_his = get_history(count=60, frequency='1d', field=['close','low','high'], security_list=sec, fq='pre', include=False)
        sec_his['up'] = sec_his['high'].shift(1).rolling(window=g.config['n1']).max()   #上线
        sec_his['down'] = sec_his['low'].shift(1).rolling(window=g.config['n2']).min()   #下线
        
        high, low, close = sec_his['high'], sec_his['low'], sec_his['close']
        trueHigh = high.where(high>(close.shift(1)), (close.shift(1)))
        trueLow = low.where(low<(close.shift(1)), (close.shift(1)))
        atr = (trueHigh - trueLow)[-g.config['ATR']:].mean()
        sell=0
        if sec in today_sell:
            sell=1      #当日清仓的当日不再买入
            
        yesterday_close = close[-1]       
        limt_prc=yesterday_close*g.config['buy_field']    #买入限价，昨日收盘价基础上涨幅1-2%       
        
        posInfo = get_position(sec)
        price = posInfo.last_sale_price
        positions = get_positions()
        #position_count = len(positions)
        position_count = sum(1 for code, pos in positions.items() if pos.amount > 0)   #持仓股票个数
        
        holdRet = posInfo.last_sale_price/posInfo.cost_basis-1 if posInfo.cost_basis!=0 else 0
        if posInfo.enable_amount>0:
            # 减仓
            if sec_his['low'][-1] <=  posInfo.cost_basis - atr:
                vol = min(posInfo.enable_amount, g.config['buy_amount']*g.config['减仓ATR']/atr//100*100)
                order(sec, -vol)
                log.info('减仓')
                    
            # 加仓
            elif holdRet>0 and sec_his['high'][-1] >= posInfo.last_sale_price + 0.5*atr and limt_prc>price:
                vol = min(context.portfolio.cash/price, g.config['buy_amount']*g.config['加仓ATR']/atr)//100*100
                if (posInfo.amount * price + vol * price) > g.config['max_position_amount']:
                    vol = (g.config['max_position_amount'] - posInfo.amount * price) // price
                if vol > 0 :
                    order(sec, vol)
                    log.info('加仓')
                    
        if posInfo.amount==0:
            #入场，当天清仓的不买入，跌停不买，不超过最大持股个数
            if sec_his['high'][-1] > sec_his['up'][-1] and sell==0 and check_limit(sec)!=-1 and limt_prc>price and position_count<g.config['sec_max']: 
                vol = min(context.portfolio.cash/price, g.config['buy_amount']*g.config['入场ATR']/atr)//100*100   #计算买入数量并取整百
                if vol > 0 :
                    order(sec, vol)
                    log.info('开仓')
                   

def handle_data(context, data):
    pass