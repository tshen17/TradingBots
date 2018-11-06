from __future__ import division
from tradersbot import TradersBot

import sys
import math
from statistics import mean
from scipy.stats import norm
import datetime
import time
import random
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from py_vollib.black.implied_volatility import implied_volatility as iv
from py_vollib.black.greeks.analytical import delta, gamma, vega


t = TradersBot(host=sys.argv[1], id=sys.argv[2], password=sys.argv[3])

START_TIME = time.time()

def exp_time():
    global START_TIME
    return (7.5 * 60 - (time.time() - START_TIME)) / (7.5 * 60 * 12)

DELTA_MAX = 1000
VEGA_MAX = 9000

INTEREST_RATE = 0
TRADE_FEE = 0.005
OPTIONS_LIM = 5000
FUTURES_LIM = 2500
WINDOW = 10

# TODO: Make volatility prediction model (basic smile?), update strategy to keep track of current bids, market make

# TRADE STRATEGY
# 1. Use Bollinger Bands on price as baseline (in simulation, returns $14,000 PNL in one round)
# 2.

# 1. Exploit inconsistencies in implied volatility across different strike prices
# 2. Market make when spreads are large, without becoming overly exposed to risk
# 3. Hedge positions to reduce risk

# Our portfolio. Keeps track of:
# List of our securities
# - all default information
# - calculated implied volatility (calculated using Black-Scholes)
# Greeks of our portfolio

PORTFOLIO = {}
PORTFOLIO['positions'] = {}
PORTFOLIO['money'] = 1000000
PORTFOLIO['options'] = 0
PORTFOLIO['futures'] = 0
PORTFOLIO['greeks'] = {}
PORTFOLIO['greeks']['delta'] = 0
PORTFOLIO['greeks']['gamma'] = 0
PORTFOLIO['greeks']['vega'] = 0

# Our copy of the market. Keeps track of:
# List of all available securities
# - all default information
# - implied volatility
# Underlying
# - spot
# - volatility

MARKET = {}

## GREEKS

# Calculates delta
def calc_delta(call, S, K, T, r, sig):
    d1 = (math.log(S/K) + (r + sig ** 2 / 2) * T) / (sig * math.sqrt(T))
    return norm.cdf(d1) - 1 + call

# Calculates gamma
def calc_gamma(S, K, T, r, sig):
    d1 = (math.log(S/K) + (r + sig ** 2 / 2) * T) / (sig * math.sqrt(T))
    return norm.pdf(d1) / (S * sig * sqrt(T))

# Calculates vega
def calc_vega(S, K, T, r, sig):
    d1 = (math.log(S/K) + (r + sig ** 2 / 2) * T) / (sig * math.sqrt(T))
    return S * norm.pdf(d1) * math.sqrt(T)

## VOLATILITY

# Calculates price as given by Black-Scholes model
def calc_price(call, S, K, T, r, sig):
    d1 = (math.log(S/K) + (r + sig ** 2 / 2) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    call_price = norm.cdf(d1) * S - norm.cdf(d2) * K * math.exp(-r * T)
    if call:
        return call_price
    else:
        # using put-call parity
        return call_price + K * math.exp(-r * T) - S

# Calculates implied volatility
def calc_vol(P, S, K, T, r):
    #initial guess
    sig = 0.5

    max_iter = 10
    thresh = 1e-4
    eps = 1

    i = 0
    for i in range(max_iter):
        if eps < thresh:
            return sig
        diff = calc_price(1, S, K, T, r, sig) - P
        vega = calc_vega(S, K, T, r, sig)
        if vega == 0:
            return (S, K, T, r, sig)
        sig =  -diff/vega + sig
        eps = abs(diff)
    print("Implied volatility = ", sig)
    print("Num iterations = ", i)
    return sig

# Plots implied volatility smile
def plot_vol(type):
    # Live plots volatility
    fig = plt.figure()
    ax1 = fig.add_subplot(1,1,1)

    def animate(i):
        strike = []
        iv = []
        for security in MARKET:
            if MARKET[security]['type'] == type:
                strike.append(MARKET[security]['strike'])
                iv.append(MARKET[security]['cur_iv'])
        ax1.clear()
        ax1.scatter(strike,iv)
    ani = animation.FuncAnimation(fig, animate, interval=1000)
    #plt.show()

def make_order(order, type, security, quant, price):
    d = quant*delta(MARKET[security]['type'], 100, MARKET[security]['strike'], exp_time(), INTEREST_RATE, MARKET[security]['cur_iv'])
    g = quant*gamma(MARKET[security]['type'], 100, MARKET[security]['strike'], exp_time(), INTEREST_RATE, MARKET[security]['cur_iv'])
    v = quant*vega(MARKET[security]['type'], 100, MARKET[security]['strike'], exp_time(), INTEREST_RATE, MARKET[security]['cur_iv'])

    if security not in PORTFOLIO:
        PORTFOLIO['positions'][security] = {}
        PORTFOLIO['positions'][security]['quant'] = 0
        PORTFOLIO['positions'][security]['delta'] = 0
        PORTFOLIO['positions'][security]['gamma'] = 0
        PORTFOLIO['positions'][security]['vega'] = 0

    if type == 'buy':
        order.addBuy(security, quantity=quant, price=price)
        print("BUY", security, ": ", quant, " @", price)
        PORTFOLIO['positions'][security]['quant'] += quant
        PORTFOLIO['positions'][security]['price'] = price
        PORTFOLIO['positions'][security]['delta'] += d
        PORTFOLIO['positions'][security]['gamma'] += g
        PORTFOLIO['positions'][security]['vega'] += v
        PORTFOLIO['greeks']['delta'] += d
        PORTFOLIO['greeks']['gamma'] += g
        PORTFOLIO['greeks']['vega'] += v
        PORTFOLIO['options'] += quant
    elif type == 'sell':
        order.addSell(security, quantity=quant, price=price)
        print("SELL", security, ": ", quant, " @", price)
        PORTFOLIO['positions'][security]['quant'] -= quant
        PORTFOLIO['positions'][security]['delta'] -= d
        PORTFOLIO['positions'][security]['gamma'] -= g
        PORTFOLIO['positions'][security]['vega'] -= v
        PORTFOLIO['greeks']['delta'] -= d
        PORTFOLIO['greeks']['gamma'] -= g
        PORTFOLIO['greeks']['vega'] -= v
        PORTFOLIO['options'] += quant


def make_market(order):
    for security in MARKET.keys():
        if security != "TMXFUT" and MARKET[security]['spreads'][-1] > mean(MARKET[security]['spreads']) * 2.5:
            price1, quant1 = mean([MARKET[security]['mn_bid'],MARKET[security]['min_bid']]), 10
            price2, quant2 = mean([MARKET[security]['max_ask'], MARKET[security]['mn_ask']]), 10

            # TODO: Check to see if cur prices are better than previous prices, and if there are open orders.
            if price1 > MARKET[security]['intrinsic']:
                print("MM Spread: ", price2 - price1)
                make_order(order, 'buy', security, quant1, round(price1 - 0.3, 2))
                make_order(order, 'sell', security, quant2, round(price2, 2))




def bb_strategy(order):
    for security in MARKET.keys():
        if len(MARKET[security]['prices']) > WINDOW:
            s = pd.DataFrame(MARKET[security]['prices'])
            MARKET[security]['MA'] = s.rolling(window=WINDOW, min_periods=1).mean()
            MARKET[security]['STD'] = s.rolling(window=WINDOW, min_periods=1).std()
            MARKET[security]['Upper'] = MARKET[security]['MA'] + (MARKET[security]['STD'] * 2)
            MARKET[security]['Lower'] = MARKET[security]['MA'] - (MARKET[security]['STD'] * 2)
            MARKET[security]['MA'] = MARKET[security]['MA'].values.flatten().tolist()
            MARKET[security]['STD'] = MARKET[security]['STD'].values.flatten().tolist()
            MARKET[security]['Upper'] = MARKET[security]['Upper'].values.flatten().tolist()
            MARKET[security]['Lower'] = MARKET[security]['Lower'].values.flatten().tolist()

            # Bollinger Bands Strategy
            if security != "TMXFUT":
                if MARKET[security]['cur_iv'] < 0.8 * mean(MARKET[security]['ivs']) and MARKET[security]['prices'][-1] < MARKET[security]['Lower'][-1] and MARKET[security]['prices'][-2] > MARKET[security]['Lower'][-2] * 0.95:
                    # price, quant = min(MARKET[security]["bids"].items(), key=lambda x: x[0])
                    # quant = 10
                    price, quant = MARKET[security]['cur_price'], 10
                    time_val = price - MARKET[security]['intrinsic']

                    if time_val > 0:
                        time_val = 0.1 * time_val if 0.1 * time_val > 0.5 else 0.5
                        print("BB: ", end='')
                        make_order(order, 'buy', security, quant, round(price - time_val, 2))
                    # Move this to onTrade because you only update when the trade actually happens

                elif MARKET[security]['cur_iv'] > 1.20 * mean(MARKET[security]['ivs']) and MARKET[security]['prices'][-1] > MARKET[security]['Upper'][-1] and MARKET[security]['prices'][-2] < MARKET[security]['Upper'][-2] * 1.05:
                    # price, quant = min(MARKET[security]["bids"].items(), key=lambda x: x[0])
                    # quant = 10
                    price, quant = MARKET[security]['cur_price'], 10
                    time_val = price - MARKET[security]['intrinsic']
                    if time_val > 0:
                        time_val = 0.1 * time_val if 0.1 * time_val > 0.5 else 0.5
                        print("BB: ", end='')
                        make_order(order, 'sell', security, quant, round(price + time_val, 2))



                if PORTFOLIO['greeks']['delta'] > DELTA_MAX:
                    print("DELTA LIMIT PASSED: ", PORTFOLIO['greeks']['delta'])
                if PORTFOLIO['greeks']['vega'] > VEGA_MAX:
                    print("VEGA LIMIT PASSED: ", PORTFOLIO['greeks']['vega'])

## CALLBACKS

# Initializes the prices
def ack_register_method(msg, order):
    global MARKET
    security_dict = msg['case_meta']['securities']
    for security in security_dict.keys():
        if not(security_dict[security]['tradeable']):
            continue
        type = security[-1].lower()
        price = security_dict[security]['starting_price']
        MARKET[security] = {}
        MARKET[security]['type'] = type
        MARKET[security]['cur_price'] = price
        MARKET[security]['prices'] = []
        MARKET[security]['spreads'] = []
        #MARKET[security]['price'] = [price]
        if security != "TMXFUT":
            strike = int(security[1:-1])
            MARKET[security]['strike'] = strike
            intrinsic = (100 - strike) * (MARKET[security]['type'] == 'c')
            MARKET[security]['intrinsic'] = intrinsic if intrinsic > 0 else 0
            MARKET[security]['cur_iv'] = iv(price, 100, strike, INTEREST_RATE, 1/12, type)
            MARKET[security]['ivs'] = []
    print(MARKET)


# Updates latest price periodically
def market_update_method(msg, order):
    global MARKET
    security = msg['market_state']['ticker']
    MARKET[security]['cur_price'] = msg['market_state']['last_price']
    MARKET[security]['prices'].append(MARKET[security]['cur_price'])

    #bids, q1 = zip(*msg['market_state']['bids'].items())
    bids = list(msg['market_state']['bids'].keys())
    bids = [float(i) for i in bids]
    #asks, q2 = zip(*msg['market_state']['asks'].items())
    asks = list(msg['market_state']['asks'].keys())
    asks = [float(i) for i in asks]

    #print(bids, asks)

    # MARKET[security]['bids'] = bids
    # MARKET[security]['asks'] = asks
    #
    a_mn = mean(asks)
    b_mn = mean(bids)

    a_min = min(asks)
    a_max = max(asks)
    b_min = min(bids)
    b_max = max(bids)

    MARKET[security]['mn_ask'] = a_mn
    MARKET[security]['min_ask'] = a_min
    MARKET[security]['max_ask'] = a_max
    MARKET[security]['mn_bid'] = b_mn
    MARKET[security]['min_bid'] = b_min
    MARKET[security]['max_bid'] = b_max
    MARKET[security]['spreads'].append(a_mn - b_mn)



    #print("bids: ", MARKET[security]['bids'])
    #print("asks: ", MARKET[security]['asks'])
    if security != "TMXFUT":
        try:
            MARKET[security]['cur_iv'] = iv(MARKET[security]['cur_price'], 100, MARKET[security]['strike'], INTEREST_RATE, exp_time(), MARKET[security]['type'])
            MARKET[security]['ivs'].append(MARKET[security]['cur_iv'])
        except:
            MARKET[security]['cur_iv'] = 0
            MARKET[security]['ivs'].append(MARKET[security]['cur_iv'])
            #print(security)

        # if security != "TMXFUT":
        #     MARKET[security]['ivs'].append(MARKET[security]['cur_iv'])
        # print(MARKET[security]['prices'])
        # print(MARKET[security]['ivs'])
    # plot_vol('c')


# Updates market and portfolio state after each trade
def trade_method(msg, order):
    global MARKET
    print('TRADE')
    trade_dict = msg['trades']
    for trade in trade_dict:
        security = trade["ticker"]
        MARKET[security]['cur_price'] = trade["price"]
        MARKET[security]['prices'].append(MARKET[security]['cur_price'])
        #security['price'].append(trade["price"])
        # security['vol'] = calc_vol(security['type'] == 'C', trade['price'], 100, security['strike'], exp_time(), INTEREST_RATE)

        # still some weird errors with IV calculation
        if security != "TMXFUT":
            try:
                MARKET[security]['cur_iv'] = iv(MARKET[security]['cur_price'], 100, MARKET[security]['strike'], INTEREST_RATE, exp_time(), MARKET[security]['type'])
                MARKET[security]['ivs'].append(MARKET[security]['cur_iv'])
            except:
                MARKET[security]['cur_iv'] = 0
                MARKET[security]['ivs'].append(MARKET[security]['cur_iv'])
                #print(security, MARKET[security]['cur_price'], MARKET[security]['strike'], exp_time(), MARKET[security]['cur_iv']);
    #print(MARKET['T89C'])

# Buy and sell here
def trader_update_method(msg, order):
    global MARKET
    print('TRADER UPDATE\n')

    bb_strategy(order)
    #make_market(order)


        # Basic trading strategies to test program (some bugs to fix)

        # if security != "TMXFUT" and MARKET[security]['cur_iv'] < 0.8 * mean(MARKET[security]['ivs']):
        #     print("BUY (IV) ", security, ": 10 @", MARKET[security]['cur_price'])
        #     order.addBuy(security, quantity=10, price=MARKET[security]['cur_price'])
        # elif security != "TMXFUT" and MARKET[security]['cur_iv'] > 1.25 * mean(MARKET[security]['ivs']):
        #     print("SELL (IV) ", security, ": 10 @", MARKET[security]['cur_price'])
        #     order.addSell(security, quantity=10, price=MARKET[security]['cur_price'])
        #
        # if MARKET[security]['cur_price'] < 0.8 * mean(MARKET[security]['prices']):
        #     print("BUY (AVG) ", security, ": 10 @", MARKET[security]['cur_price'])
        #     order.addBuy(security, quantity=10, price=MARKET[security]['cur_price'])
        # elif MARKET[security]['cur_price'] > 1.25 * mean(MARKET[security]['prices']):
        #     print("SELL (AVG) ", security, ": 10 @", MARKET[security]['cur_price'])
        #     order.addSell(security, quantity=10, price=MARKET[security]['cur_price'])

t.onAckRegister = ack_register_method
t.onMarketUpdate = market_update_method
t.onTraderUpdate = trader_update_method
t.onTrade = trade_method
#t.onAckModifyOrders = ack_modify_orders_method
#t.onNews = news_method
t.run()
