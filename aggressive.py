# aggressive_taker.py
import json
import os

import commons


def get_price_per_buy(current_value, num_buys, maker_taker):
    # if maker_taker == "taker":
    price_per_buy_before_fees = current_value / num_buys
    fees = price_per_buy_before_fees * .00075
    return price_per_buy_before_fees - fees
    # else:
    #     return current_value / num_buys


def aggressive_trade(exchange, current_value, buys, sells, portfolio, maker_taker):
    portfolio = commons.zero_out_portfolio(portfolio)
    num_buys = len(buys)
    # divide value among buys
    price_per_buy = get_price_per_buy(current_value, num_buys, maker_taker)
    for buy in buys:
        try:
            j = json.dumps(exchange.fetchTicker(buy + "/USD"), indent=4, sort_keys=True)
        except Exception as e:
            print("** FAULTY LOGIC **")
            print(e)
            portfolio[buy] = price_per_buy  # TODO This is faulty logic
        else:
            c = commons.json_to_candle(j)
            portfolio[buy] = price_per_buy / c.c
            print("buy " + str(portfolio[buy]) + " shares of " + buy + " for " + str(price_per_buy))
    return portfolio


def aggressive_backtest_trade(buy_prices, current_value, buys, sells, portfolio, maker_taker):
    portfolio = commons.zero_out_portfolio(portfolio)
    num_buys = len(buys)
    # divide value among buys
    price_per_buy = get_price_per_buy(current_value, num_buys, maker_taker)
    for buy in buys:
        portfolio[buy] = float(price_per_buy) / buy_prices[buy]
        print("buy " + str(portfolio[buy]) + " shares of " + buy + " for " + str(price_per_buy) + " at $" + str(buy_prices[buy]))
    print("trade")
    print(portfolio)
    return portfolio


def main(event, context):
    maker_taker = os.environ['maker_taker']
    trade_style = os.environ['trade_style']
    prod = os.environ['prod']
    print("Prod: " + prod)
    if prod == "true":
        commons.go_live(event, aggressive_trade, aggressive_backtest_trade, maker_taker, trade_style)
    else:
        commons.go(event, aggressive_trade, aggressive_backtest_trade, maker_taker, trade_style)


if __name__ == "__main__":
    main('', '')
