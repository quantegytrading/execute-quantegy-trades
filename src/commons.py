# aggressive_taker.py
import decimal
from datetime import datetime
from decimal import Decimal

import boto3
import ccxt
import json
import os
import time
from dataclasses import dataclass
from botocore.exceptions import ClientError
from slack_sdk import WebClient
from ccxt import InvalidOrder, BadSymbol, InsufficientFunds
import time


@dataclass
class Candle:
    def __init__(self, dt: str, s: str, o: float, h: float, l: float, c: float, u: str):
        self.s = s
        self.o = o
        self.c = c
        self.h = h
        self.l = l
        self.dt = dt
        self.u = u


def json_to_candle(raw: str):
    o: str = ""
    c: str = ""
    h: str = ""
    l: str = ""
    s: str = ""
    sym: str = ""
    dt: str = ""
    u: str = ""

    json_object = json.loads(raw)
    for k in json_object.keys():
        if k == "symbol":
            s = json_object[k]
        if k == "open":
            o = json_object[k]
        if k == "close":
            c = json_object[k]
        if k == "high":
            h = json_object[k]
        if k == "low":
            l = json_object[k]
        if k == "datetime":
            d = json_object[k]
            date = datetime.strptime(d, '%Y-%m-%dT%H:%M:%S.%fZ')
            dt = d[:-8]
            unix = time.mktime(date.timetuple())
            u = str(unix)
    last_chars = s[-4:]
    if last_chars == "/USD":
        sym = s[:-4]
    return Candle(dt, sym, o, h, l, c, u)


def init_exchange():
    exchange_class = getattr(ccxt, os.environ['eid'])
    exchange = exchange_class({
        'apiKey': os.environ['key'],
        'secret': os.environ['secret'],
        'timeout': 30000,
        'enableRateLimit': True,
    })
    try:
        exchange.loadMarkets()
        print("Exchange Loaded")
    except Exception as e:
        print(e)
    return exchange


def get_portfolio_id(algo, env, interval, maker_taker, trade_style):
    portfolio_id = algo + "-" + env + "-" + interval + "-" + trade_style + "-" + maker_taker
    print(portfolio_id)
    return portfolio_id


def get_env(source_arn: str) -> str:
    if source_arn.find("backtest") != -1:
        return "backtest"
    else:
        return "soak"


def get_target_arn(source_arn: str) -> str:
    if source_arn.find("backtest") != -1:
        return "arn:aws:sns:us-east-1:716418748259:log-quantegy-data-backtest"
    else:
        return "arn:aws:sns:us-east-1:716418748259:log-quantegy-data-soak"


def sell_portfolio(portfolio, sells, exchange):
    usd = 0
    for key in portfolio.keys():
        if key in sells:
            # get current value of sell
            j = json.dumps(exchange.fetchTicker(key + "/USD"), indent=4, sort_keys=True)
            c = json_to_candle(j)
            usd = usd + float(c.c)
            # add current value of sell to USD
            portfolio[key] = 0
    print("selling")
    print(portfolio)
    usd = usd + float(portfolio.get('USDT'))
    portfolio['USDT'] = str(usd)
    return portfolio


def zero_out_portfolio(portfolio):
    for key in portfolio.keys():
        portfolio[key] = 0
    print("zero")
    print(portfolio)
    return portfolio


def get_current_portfolio_value(exchange, portfolio):
    current_value = 0
    for key in portfolio.keys():
        if portfolio[key] > 0:
            # get current price
            c = json_to_candle(json.dumps(exchange.fetchTicker(key + "/USD"), indent=4, sort_keys=True))
            current_value = current_value + (c.c * float(portfolio[key]))
    return current_value


def get_backtest_portfolio_value(price_guide, portfolio):
    current_value = 0
    for key in portfolio.keys():
        if portfolio[key] > 0:
            if key in price_guide:  # if price is in the guide then use it
                current_value = float(current_value) + (float(portfolio[key]) * float(price_guide[key]))
            else:  # if it is not in the guide use it as a dollar tether
                current_value = float(current_value) + (float(portfolio[key]))
    return current_value


def get_current_live_portfolio_value(exchange, portfolio) -> str:
    usd = exchange.fetchBalance().get('total').get('USDT')
    curr_val = float(usd)
    try:
        for symbol in portfolio:
            if symbol != 'USDT':
                ticker = exchange.fetchTicker(symbol + "/USDT")
                count = portfolio.get(symbol)
                curr_val = curr_val + (float(count) * float(ticker.get('ask')))
    except Exception as e:
        print(e)
    return str(curr_val)


def get_current_btc_value(exchange) -> str:
    ticker = exchange.fetchTicker("BTC/USD")
    btc_value = float(ticker.get('ask')) * 0.03195139
    return str(btc_value)


def update_portfolio_table(client_id, portfolio, table):
    # update dynamo with new portfolio
    data = {
        'client-id': client_id,
        'portfolio': portfolio,
    }
    ddb_data = json.loads(json.dumps(data), parse_float=Decimal)
    try:
        print("putting item")
        table.put_item(Item=ddb_data)
    except ClientError as e:
        print(e)


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return (str(o) for o in [o])
        return super(DecimalEncoder, self).default(o)


def go(event, trade_fn, backtest_trade_fn, maker_taker, trade_style):
    sns = boto3.client('sns')
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('portfolio-data')
    exchange = init_exchange()
    event_message = json.loads(event['Records'][0]['Sns']['Message'])
    print(event_message)
    source_arn = event['Records'][0]['Sns']['TopicArn']
    algorithm = event_message['algorithm']
    interval = event_message['interval']
    exchange_name = event_message['exchange']
    backtest_time = event_message['backtest-time']
    env = get_env(event_message['env'])
    buys: list = event_message['buys']
    sells: list = event_message['sells']
    portfolio_id = get_portfolio_id(algorithm, env, interval, maker_taker, trade_style)
    get_response = table.get_item(Key={'client-id': portfolio_id})
    portfolio = get_response['Item']['portfolio']
    print("before")
    print(portfolio)
    for key in portfolio.keys():
        value = portfolio.get(key)
        portfolio[key] = float(value)

    print("after")
    print(portfolio)
    num_buys = len(buys)
    buy_prices = event_message['buy_prices']

    if env == 'soak':
        current_value = get_current_portfolio_value(exchange, portfolio)
    else:
        current_value = get_backtest_portfolio_value(buy_prices, portfolio)
    print("portfolio value before: " + str(current_value))

    if num_buys > 0:
        if env == 'soak':
            portfolio = trade_fn(exchange, current_value, buys, sells, portfolio, maker_taker)
            current_value = get_current_portfolio_value(exchange, portfolio)
        else:
            portfolio = backtest_trade_fn(buy_prices, current_value, buys, sells, portfolio, maker_taker)
            current_value = get_backtest_portfolio_value(buy_prices, portfolio)
        update_portfolio_table(portfolio_id, portfolio, table)

    btc_value = get_current_btc_value(exchange)

    message = {
        'current_value': str(current_value),
        'btc_value': btc_value,
        'portfolio_id': portfolio_id,
        'algorithm': algorithm,
        'exchange': exchange_name,
        'portfolio': portfolio,
        'buys': json.dumps(buys),
        'sells': json.dumps(buys),
        'env': env,
        'backtest-time': backtest_time
    }

    target_arn = get_target_arn(source_arn)
    print("message = " + str(message))
    print("portfolio value after: " + str(current_value))
    sns.publish(
        TargetArn="arn:aws:sns:us-east-1:716418748259:log-quantegy-data-soak",
        Message=json.dumps(message, cls=DecimalEncoder)
    )


def truncate_float(f) -> float:
    ff = format(f, '.10f')
    s = str(ff)
    xs = s.split('.')
    return float(xs[0] + '.' + xs[1][:6])


def slack_post(msg: str):
    client = WebClient(token=os.environ['slack_token'])
    client.chat_postMessage(channel=f"#quantegy-crypto", text=msg, icon_emoji=':moneybag:', username='Sportzballz')


def sym_price(syms, prices):
    sym_prices = []
    for sym in syms:
        stripped_sym = sym[:-4]
        sym_prices.append(f'{str(sym)}: ${str(prices[stripped_sym])}')
    return sorted(sym_prices)


def go_slack(event, trade_fn):
    print(event)
    event_message = json.loads(event['Records'][0]['body'])
    buys: list = event_message['buys']
    sells: list = event_message['sells']
    prices: list = event_message['prices']
    buys_prices = sym_price(buys, prices)
    sells_prices = sym_price(sells, prices)
    d = datetime.now().strftime("%m/%d %H:%M:")
    slack_post(f'```{d}\nbuys:\n{"\n".join(map(str, buys_prices))}```\n```sells:\n{"\n".join(map(str, sells_prices))}```')
    time.sleep(1)
    # for buy in buys_prices:
    #     slack_post(str(buy))
    #     time.sleep(1)
    # slack_post(datetime.now().strftime("%m/%d %H:%M: ") + "sells: ")
    # time.sleep(1)
    # for sell in sells_prices:
    #     slack_post(str(sell))
    #     time.sleep(1)



def go_live(event, trade_fn):
    print("go_live")
    exchange = init_exchange()
    event_message = json.loads(event['Records'][0]['body'])
    print(event_message)
    algorithm = event_message['algorithm']
    exchange_name = event_message['exchange']
    backtest_time = event_message['backtest-time']
    env = "prd"
    buys: list = event_message['buys']
    sells: list = event_message['sells']
    print("BUYS/SELLS: " + str(buys) + " / " +str(sells))
    trade_fn(exchange, buys, sells)
    portfolio = dict()
    symbols = exchange.fetchBalance()
    for (k,v) in symbols.get('free').items():
        if float(v) > 0:
            portfolio[k] = float(v)

    current_value = get_current_live_portfolio_value(exchange, portfolio)
    # btc_value = get_current_btc_value(exchange)

    message = {
        'current_value': current_value,
        'btc_value': "0.00",
        'portfolio_id': "prd",
        'algorithm': algorithm,
        'exchange': exchange_name,
        'portfolio': portfolio,
        'buys': json.dumps(buys),
        'sells': json.dumps(sells),
        'env': env,
        'backtest-time': backtest_time
    }

    print("message = " + str(message))
    print("portfolio value after: " + current_value)
