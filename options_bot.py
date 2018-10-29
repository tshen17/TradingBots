from tradersbot import TradersBot

import math
from scipy.stats import norm
import datetime
import time
import random
from py_vollib import black_scholes


t = TradersBot('127.0.0.1', 'trader0', 'trader0')

START_TIME = time.time()

def exp_time():
    global START_TIME
    return (time.time() - START_TIME) / (7.5 * 60 * 12)

DELTA_MAX = 1000
VEGA_MAX = 9000

INTEREST_RATE = 0
TRADE_FEE = 0.005
OPTIONS_LIM = 5000
FUTURES_LIM = 2500

# 1. Exploit inconsistencies in implied volatility across different strike prices
# 2. Market make when spreads are large, without becoming overly exposed to risk
# 3. Hedge positions to reduce risk

# Our portfolio. Keeps track of:
# List of our securities
# - all default information
# - calculated implied volatility (calculated using Black-Scholes)
# Greeks of our portfolio

PORTFOLIO = {}

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
        MARKET[security]['price'] = price
        if security != "TMXFUT":
            strike = int(security[1:-1])
            MARKET[security]['strike'] = strike
            MARKET[security]['vol'] = black_scholes.implied_volatility.implied_volatility(price, 100, strike, 1/12, INTEREST_RATE, type)


# Updates latest price periodically
def market_update_method(msg, order):
    global MARKET
    # print(MARKET)
    # MARKET[msg['market_state']['ticker']]['price'] = msg['market_state']['last_price']

# Updates market state after each trade
def trade_method(msg, order):
    global MARKET
    print(msg, '\n')
    trade_dict = msg['trades']
    for trade in trade_dict:
        security = MARKET[trade["ticker"]]
        security['price'] = trade["price"]
        # security['vol'] = calc_vol(security['type'] == 'C', trade['price'], 100, security['strike'], exp_time(), INTEREST_RATE)
        security['vol'] = black_scholes.implied_volatility.implied_volatility(security['price'], 100, security['strike'], exp_time(), INTEREST_RATE, security['type'])


# Buys or sells in a random quantity every time it gets an update
# You do not need to buy/sell here
def trader_update_method(msg, order):
    global MARKET
    positions = msg['trader_state']['positions']
    for security in positions.keys():
        if random.random() < 0.5:
            quant = 10*random.randint(1, 10)
            order.addBuy(security, quantity=quant,price=MARKET[security]['price'])
        else:
            quant = 10*random.randint(1, 10)
            order.addSell(security, quantity=quant,price=MARKET[security]['price'])


t.onAckRegister = ack_register_method
t.onMarketUpdate = market_update_method
t.onTraderUpdate = trader_update_method
t.onTrade = trade_method
#t.onAckModifyOrders = ack_modify_orders_method
#t.onNews = news_method
t.run()
