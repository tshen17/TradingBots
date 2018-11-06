from tradersbot import *
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

#Initialize variables: positions, expectations, future customer orders, etc
position_limit = 5000
case_length = 450
cash = 0
C = 1/25000.
position_lit = 0
position_dark = 0
time = 0
topBid = 0
topAsk = 0
news_history = {}
MARKET = {}
statistics = {} #keep track of mean and standard deviation of a normal distribution (starting at 0.5, 0.5)
#for how much each person's orders match with fluctuations in p0.
#etc etc

##Objectives:
#Keep track of the order size made by each customer, and observe whether the LIT market price goes up proportional the order size after 8 ticks. If so, you have more confidence about who has insider information. So if they buy lots, you can expect the price to go up, and you should buy stuff at the lower price fast.

#keep track of the position of the market maker based on the bids people are making,
#use news events to update the probability that each customer on the dark market has insider info,
#buy/sell at a price between the current price and expected price after change

def register(msg, order):
    #Set case information
    global MARKET, time
    time = msg['elapsed_time']
    security_dict = msg['case_meta']['securities']
    for security in security_dict.keys():
        if not(security_dict[security]['tradeable']):
            continue
        price = security_dict[security]['starting_price']
        MARKET[security] = {}
        MARKET[security]['cur_price'] = price
        MARKET[security]['prices'] = []
        MARKET[security]['cur_bids'] = msg['market_states'][security]['bids']
        MARKET[security]['cur_asks'] = msg['market_states'][security]['asks']
        #MARKET[security]['price'] = [price]
    news_sources = msg['case_meta']['news_sources']
    for source in news_sources.keys():
        news_history[source] = []
        statistics[source] = {'mean': 0.5, 'std': 0.5}
    MARKET['cur_news'] = []
    #print(MARKET)

def update_market(msg, order):
    #Update market information
    global MARKET, time, C
    time = msg['elapsed_time']
    security = msg['market_state']['ticker']
    MARKET[security]['cur_price'] = msg['market_state']['last_price']
    MARKET[security]['prices'].append(MARKET[security]['cur_price'])
    MARKET[security]['cur_bids'] = msg['market_state']['bids']
    MARKET[security]['cur_asks'] = msg['market_state']['asks']

    if len(MARKET['cur_news']) > 0:
        if time >= int(MARKET['cur_news'][0][3]) + 9: #Check how much the order actually affects p0 (zero-th level approx):
            change = MARKET['TRDRS.LIT']['cur_price']-MARKET['cur_news'][0][4] #The first order, and price at the time.
            print(change, C, MARKET['cur_news'][0][1])
            proportion = change/(C*MARKET['cur_news'][0][1])
            if MARKET['cur_news'][0][2] == 'sell':
                proportion = -proportion
            print(proportion)
            source = MARKET['cur_news'][0][0]
            mean = statistics[source]['mean']
            std = statistics[source]['std']
            updated_mean = (mean+std**2*proportion)/(1+std**2) #updating with the assumption of a 1 std for the data point. Might need to adjust this.
            updated_std = ((std**2)/(1+std**2))**0.5
            print(updated_mean, updated_std)
            statistics[source]['mean'] = updated_mean
            statistics[source]['std'] = updated_std
            MARKET['cur_news'].pop(0) #remove the oldest order news


def update_trader(msg, order):
    #Update positions
    global MARKET, time, position_dark, position_lit
    #position_dark = int(msg['trader_state']['positions']['TRDRS.DARK'])
    #position_lit = int(msg['trader_state']['positions']['TRDRS.LIT'])
    if len(msg['trader_state']['open_orders'].keys()) > 0: #Cancel bad outstanding orders
        usr = msg['trader_state']['open_orders'].keys()[0]
        security = msg['trader_state']['open_orders'][usr]['ticker']
        if msg['trader_state']['open_orders'][usr]['buy'] and msg['trader_state']['open_orders'][usr]['price'] > MARKET[security]['cur_price']:
            order.addCancel(security, msg['trader_state']['open_orders'][usr]['order_id'])
    if case_length-time < 90:
        if position_dark > 0:
            order.addSell('TRDRS.DARK', quantity=position_dark, price=MARKET['TRDRS.DARK']['cur_price'])
            position_dark = 0
        elif position_dark < 0:
            order.addBuy('TRDRS.DARK', quantity=position_dark, price=MARKET['TRDRS.DARK']['cur_price'])
            position_dark = 0
        if position_lit > 0:
            if position_lit > 1000:
                order.addSell('TRDRS.LIT', quantity=1000, price=MARKET['TRDRS.LIT']['cur_price'])
                position_lit = position_lit - 1000
            else:
                order.addSell('TRDRS.LIT', quantity=position_lit, price=MARKET['TRDRS.LIT']['cur_price'])
                position_lit = 0
        elif position_lit < 0:
            if position_lit < -1000:
                order.addBuy ('TRDRS.LIT', quantity=1000, price=MARKET['TRDRS.LIT']['cur_price'])
                position_lit = position_lit + 1000
            else:
                order.addBuy('TRDRS.LIT', quantity=position_lit, price=MARKET['TRDRS.LIT']['cur_price'])
                position_lit = 0

def trade_method(msg, order):
    #Update trade information
    global MARKET
    #print('TRADE')
    trade_dict = msg['trades']
    #print(trade_dict)
    for trade in trade_dict:
        security = trade["ticker"]
        MARKET[security]['cur_price'] = trade["price"]
        MARKET[security]['prices'].append(MARKET[security]['cur_price'])

def update_order(msg, order):
    #Update order information
    pass

def update_news(msg, order):
    global MARKET, news_history, C, position_dark, position_lit
    #Update news information
    source = msg['news']['source']
    amount = int(msg['news']['body'])
    time = int(msg['news']['time'])
    headline = msg['news']['headline']
    print(headline)
    if case_length-time < 90:
        pass
    #bypass the next parts in the last 30 seconds. Make no new orders.
    elif "buying" in headline:
        action = "buy"
        order.addSell('TRDRS.DARK', quantity=1000, price=MARKET['TRDRS.DARK']['cur_price']+statistics[source]['mean']*C*amount) #Should be market price-c*position of market maker (which you calculate by keeping track of things) + how much you're willing to bet that p0 will move, currently set at 0.25*quantity.
        order.addBuy('TRDRS.LIT', quantity = 1000, price= MARKET['TRDRS.LIT']['cur_price']+statistics[source]['mean']*C*amount) #Neutralize your overall position on TRDRS
        position_dark -= 1000
        position_lit += 1000
        MARKET['cur_news'] += [[source, amount, action, time, MARKET['TRDRS.LIT']['cur_price']]]
        news_history[source] += [[source, amount, action, time, MARKET['TRDRS.LIT']['cur_price']]]
    elif "selling" in headline:
        action = "sell"
        order.addBuy('TRDRS.DARK', quantity = 1000, price= MARKET['TRDRS.DARK']['cur_price']-statistics[source]['mean']*C*amount)
        order.addSell('TRDRS.LIT', quantity=1000, price=MARKET['TRDRS.LIT']['cur_price']-statistics[source]['mean']*C*amount)
        position_dark += 1000
        position_lit -= 1000
        MARKET['cur_news'] += [[source, amount, action, time, MARKET['TRDRS.LIT']['cur_price']]]
        news_history[source] += [[source, amount, action, time, MARKET['TRDRS.LIT']['cur_price']]]
    else:
        raise ValueError("News message contains neither buying nor selling statement. It says: ", headline)
    #print(order)

t = TradersBot(host=sys.argv[1], id=sys.argv[2], password=sys.argv[3])

t.onAckRegister = register
t.onMarketUpdate = update_market
t.onTraderUpdate = update_trader
t.onTrade = trade_method
#t.onAckModifyOrders = update_order
t.onNews = update_news

t.run()
