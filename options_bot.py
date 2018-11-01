from __future__ import division
from tradersbot import TradersBot

import math
from statistics import mean
from scipy.stats import norm
import datetime
import time
import random
import pandas as pd
from py_vollib.black.implied_volatility import implied_volatility as iv
from py_vollib.black.greeks.analytical import delta, gamma, vega


t = TradersBot('127.0.0.1', 'trader0', 'trader0')

START_TIME = time.time()

def exp_time():
    global START_TIME
    return (7.5 * 60 - (time.time() - START_TIME)) / (7.5 * 60)

DELTA_MAX = 1000
VEGA_MAX = 9000

INTEREST_RATE = 0
TRADE_FEE = 0.005
OPTIONS_LIM = 5000
FUTURES_LIM = 2500
WINDOW = 10

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
PORTFOLIO['trades'] = 0
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
        #MARKET[security]['price'] = [price]
        if security != "TMXFUT":
            strike = int(security[1:-1])
            MARKET[security]['strike'] = strike
            MARKET[security]['cur_iv'] = iv(price, 100, strike, INTEREST_RATE, 1/12, type)
            MARKET[security]['ivs'] = []
    print(MARKET)


# Updates latest price periodically
def market_update_method(msg, order):
    global MARKET
    security = msg['market_state']['ticker']
    MARKET[security]['cur_price'] = msg['market_state']['last_price']
    MARKET[security]['prices'].append(MARKET[security]['cur_price'])
    if security != "TMXFUT":
        try:
            MARKET[security]['cur_iv'] = iv(MARKET[security]['cur_price'], 100, MARKET[security]['strike'], INTEREST_RATE, exp_time(), MARKET[security]['type'])
            MARKET[security]['ivs'].append(MARKET[security]['cur_iv'])
        except:
            MARKET[security]['cur_iv'] = 0
            MARKET[security]['ivs'].append(MARKET[security]['cur_iv'])
            print(security)

        # if security != "TMXFUT":
        #     MARKET[security]['ivs'].append(MARKET[security]['cur_iv'])
        # print(MARKET[security]['prices'])
        # print(MARKET[security]['ivs'])


# Updates market state after each trade
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
        if security != "TMXFUT":
            try:
                MARKET[security]['cur_iv'] = iv(MARKET[security]['cur_price'], 100, MARKET[security]['strike'], INTEREST_RATE, exp_time(), MARKET[security]['type'])
                MARKET[security]['ivs'].append(MARKET[security]['cur_iv'])
            except:
                MARKET[security]['cur_iv'] = 0
                MARKET[security]['ivs'].append(MARKET[security]['cur_iv'])
                print(security)
    #print(MARKET['T89C'])

# Buy and sell here
def trader_update_method(msg, order):
    global MARKET
    print('TRADER UPDATE\n')

    positions = msg['trader_state']['positions']

    for security in positions.keys():

        if len(MARKET[security]['prices']) > WINDOW:
            s = pd.DataFrame(MARKET[security]['prices'])
            MARKET[security]['MA'] = s.rolling(window=WINDOW, min_periods=1).mean()
            MARKET[security]['STD'] = s.rolling(window=WINDOW, min_periods=1).std()
            MARKET[security]['Upper'] = MARKET[security]['MA'] + (MARKET[security]['STD'] * 1.25)
            MARKET[security]['Lower'] = MARKET[security]['MA'] - (MARKET[security]['STD'] * 1.25)
            MARKET[security]['MA'] = MARKET[security]['MA'].values.flatten().tolist()
            MARKET[security]['STD'] = MARKET[security]['STD'].values.flatten().tolist()
            MARKET[security]['Upper'] = MARKET[security]['Upper'].values.flatten().tolist()
            MARKET[security]['Lower'] = MARKET[security]['Lower'].values.flatten().tolist()

            # Bollinger Bands Strategy
            if MARKET[security]['prices'][-1] < MARKET[security]['Lower'][-1] and MARKET[security]['prices'][-2] < MARKET[security]['Lower'][-2]:
                print("BUY (BB) ", security, ": 10 @", MARKET[security]['cur_price'])
                order.addBuy(security, quantity=10, price=MARKET[security]['cur_price'])
                if security not in PORTFOLIO:
                    PORTFOLIO[security] = {}
                    PORTFOLIO[security]['price'] = MARKET[security]['cur_price']
                    PORTFOLIO[security]['quant'] = 10
                    PORTFOLIO[security]['delta'] = 10*delta(MARKET[security]['type'], 100, MARKET[security]['strike'], exp_time(), INTEREST_RATE, MARKET[security]['cur_iv'])
                    PORTFOLIO[security]['gamma'] = 10*gamma(MARKET[security]['type'], 100, MARKET[security]['strike'], exp_time(), INTEREST_RATE, MARKET[security]['cur_iv'])
                    PORTFOLIO[security]['vega'] = 10*vega(MARKET[security]['type'], 100, MARKET[security]['strike'], exp_time(), INTEREST_RATE, MARKET[security]['cur_iv'])
            elif MARKET[security]['prices'][-1] > MARKET[security]['Upper'][-1] and MARKET[security]['prices'][-2] < MARKET[security]['Upper'][-2]:
                print("SELL (BB) ", security, ": 10 @", MARKET[security]['cur_price'])
                order.addSell(security, quantity=10, price=MARKET[security]['cur_price'])

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
