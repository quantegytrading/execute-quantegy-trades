# handler.py
from datetime import datetime
from decimal import Decimal

import boto3
import ccxt
import json
import os
import time
from dataclasses import dataclass
from botocore.exceptions import ClientError


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
    exchange.loadMarkets()
    return exchange


def main(event, context):
    """
    TODO
    - Get customer portfolio
        - If porfolio doesnt exist, create it with 1000 USDT
    - calculate current value by calling exchange for each holding
    - split current value across all buys
    - update portfolio
    """
    sns = boto3.client('sns')
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('portfolio-data')
    exchange = init_exchange()
    trades = json.loads(event['Records'][0]['Sns']['Message'])
    current_value = 0
    message = {}
    print(str(trades))
    get_response = table.get_item(Key={'client-id': '1234'})
    portfolio = get_response['Item']['portfolio']
    print(str(get_response['Item']))

    buys: list = trades['buys']
    num_buys = len(buys)
    print("num buys: " + str(num_buys))
    if num_buys > 0:
        # set initial current value
        for key in portfolio.keys():
            if portfolio[key] > 0:
                # get current price
                c = json_to_candle(json.dumps(exchange.fetchTicker(key + "/USD"), indent=4, sort_keys=True))
                current_value = current_value + (c.c * float(portfolio[key]))

        print("portfolio value before: " + str(current_value))

        # zero out portfolio
        for key in portfolio.keys():
            portfolio[key] = 0

        # divide value among buys
        price_per_buy = current_value / num_buys
        for buy in trades['buys']:
            try:
                j = json.dumps(exchange.fetchTicker(buy + "/USD"), indent=4, sort_keys=True)
            except Exception as e:
                portfolio[buy] = price_per_buy  # TODO This is faulty logic
            else:
                c = json_to_candle(j)
                portfolio[buy] = price_per_buy / c.c
                print("buy " + str(portfolio[buy]) + " shares of " + buy + " for "+str(price_per_buy))

        # update dynamo with new portfolio
        data = {
            'client-id': '1234',
            'portfolio': portfolio
        }
        ddb_data = json.loads(json.dumps(data), parse_float=Decimal)
        try:
            print("putting item")
            table.put_item(Item=ddb_data)
        except ClientError as e:
            print(e)

        # calculate new current value
        current_value = 0
        for key in portfolio.keys():
            if portfolio[key] > 0:
                # get current price
                c = json_to_candle(json.dumps(exchange.fetchTicker(key + "/USD"), indent=4, sort_keys=True))
                current_value = current_value + (c.c * float(portfolio[key]))

    message['current_value'] = current_value
    print("message = " + str(message))
    print("portfolio value after: " + str(current_value))
    sns.publish(
        TargetArn='arn:aws:sns:us-east-1:716418748259:log-quantegy-data-soak',
        Message=json.dumps(message)
    )


if __name__ == "__main__":
    main('', '')
