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

def get_client_id(algo, env):
    if env == "backtest":
        return algo + "-" + env
    else:
        return algo


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
    event_message = json.loads(event['Records'][0]['Sns']['Message'])
    source_arn = event['Records'][0]['Sns']['TopicArn']
    algorithm = event_message['algorithm']
    exchange_name = event_message['exchange']
    env = get_env(source_arn)

    message = {}
    print(str(event_message))
    client_id = get_client_id(algorithm, env)
    get_response = table.get_item(Key={'client-id': client_id})
    portfolio = get_response['Item']['portfolio']
    current_value = 0
    print(str(get_response['Item']))

    buys: list = event_message['buys']
    num_buys = len(buys)
    print("num buys: " + str(num_buys))
    # set initial current value
    for key in portfolio.keys():
        if portfolio[key] > 0:
            # get current price
            c = json_to_candle(json.dumps(exchange.fetchTicker(key + "/USD"), indent=4, sort_keys=True))
            current_value = current_value + (c.c * float(portfolio[key]))

    print("portfolio value before: " + str(current_value))

    if num_buys > 0:
    # zero out portfolio
        for key in portfolio.keys():
            portfolio[key] = 0

        # divide value among buys
        price_per_buy = current_value / num_buys
        for buy in event_message['buys']:
            try:
                j = json.dumps(exchange.fetchTicker(buy + "/USD"), indent=4, sort_keys=True)
            except Exception as e:
                portfolio[buy] = price_per_buy  # TODO This is faulty logic
            else:
                c = json_to_candle(j)
                portfolio[buy] = price_per_buy / c.c
                print("buy " + str(portfolio[buy]) + " shares of " + buy + " for "+str(price_per_buy))

        # calculate new current value
        current_value = 0
        for key in portfolio.keys():
            if portfolio[key] > 0:
                # get current price
                c = json_to_candle(json.dumps(exchange.fetchTicker(key + "/USD"), indent=4, sort_keys=True))
                current_value = current_value + (c.c * float(portfolio[key]))

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

    formatted_portfolio = json.dumps(portfolio)
    message = {
        'current_value': current_value,
        'portfolio_id': client_id,
        'portfolio': formatted_portfolio,
        'algorithm': algorithm,
        'exchange': exchange_name,
        'env': env
    }

    target_arn = get_target_arn(source_arn)
    print("message = " + str(message))
    print("portfolio value after: " + str(current_value))
    sns.publish(
        TargetArn=target_arn,
        Message=json.dumps(message)
    )


if __name__ == "__main__":
    main('', '')
