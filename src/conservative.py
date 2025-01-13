# aggressive_taker.py
import json
import os

from ccxt import InvalidOrder, InsufficientFunds, BadSymbol

import commons


def get_price_per_buy(current_value, num_buys, maker_taker):
    price_per_buy_before_fees = current_value / num_buys
    fees = price_per_buy_before_fees * .00075
    return price_per_buy_before_fees - fees


def conservative_live_trade(exchange, buys, sells):

    ## Sell all sells to USD

    base_currency = 'USDT'
    symbols = exchange.fetchBalance()
    # print(symbols)

    for symbol in symbols.get('free'):
        if symbol not in [base_currency, 'BNB']:
            free = commons.truncate_float(symbols.get(symbol).get('free'))
            print("Free: " + str(free))
            if free > 0:
                # print(symbol + ": " + str(float(free)))
                try:
                    if symbol in sells or symbol not in buys:
                        # Do not sell for a loss
                        try:
                            symbol_pair = symbol + "/USDT"
                            trades = exchange.fetch_my_trades(symbol=symbol_pair, since=None, limit=None, params={})
                            print(trades)
                            last_trade = trades[-1]
                            purchase_price = last_trade.get('price')
                            ticker = exchange.fetchTicker(symbol_pair)
                            current_price = ticker.get('ask')
                            if current_price is None:
                                print("No current price for " + symbol)
                                current_price = 0.00
                        except Exception as e:
                            print("No trades for " + symbol)
                            purchase_price = 0.00
                        print("Selling Maybe: " + symbol + " at " + str(current_price) + " vs " + str(purchase_price))
                        if (float(purchase_price) < float(current_price) and symbol not in buys) or (symbol in sells):
                            order = exchange.createMarketSellOrder(symbol + '/' + base_currency, free)
                            print("Sold:" + symbol)
                            print(order)

                except InvalidOrder as e:
                    print(e)
                except InsufficientFunds as e:
                    print(e)
    symbols = exchange.fetchBalance()
    balance = commons.truncate_float(symbols.get(base_currency).get('free'))

    ######################################
    ## Replenish BNB - Always hold at least $10 worth for fees
    ######################################
    try:
        pair = 'BNB/USDT'
        amount_of_bnb_to_buy = 5.0
        min_bnb_holding = 1.0
        max_bnb_holding = 10.0

        symbols = exchange.fetchBalance()

        free_bnb = symbols.get('BNB').get('free')
        ticker = exchange.fetchTicker(pair)
        price = ticker.get('ask')

        holding_bnb = float(free_bnb) * float(price)
        count = amount_of_bnb_to_buy / float(price)
        try:
            if holding_bnb < min_bnb_holding:
                order = exchange.createMarketBuyOrder(pair, float(count))
                print("** BNB Re-up")
                print(order)
            if holding_bnb > max_bnb_holding:
                order = exchange.createMarketSellOrder(pair, float(count))
                print("** BNB Sell-off")
                print(order)
        except Exception as e:
            print(e)

    except Exception as e:
        print("BNB distribution exception: " + str(e))

    ######################################
    ## Buy currencies in buys list
    ######################################

    num_buys = len(buys)
    symbols = exchange.fetchBalance()
    balance = commons.truncate_float(symbols.get(base_currency).get('free'))

    # Gradient rules
    price_per_buy = 0.00

    ## TODO: Add logic for only allowing 10% of portfolio as price_per_buy
    # if balance >= (num_buys * 1000):
    #     price_per_buy = 1000.00
    if balance >= (num_buys * 100):
        price_per_buy = 100.00
    elif balance >= (num_buys * 10):
        price_per_buy = 10.00
    elif balance >= num_buys:
        price_per_buy = 1.00

    for symbol in buys:
        try:
            pair = symbol + '/' + base_currency
            ticker = exchange.fetchTicker(pair)
            price = ticker.get('ask')
            count = format(price_per_buy / price, 'f')
            print("Order: " + pair + ":" + str(count))
            order = exchange.createLimitBuyOrder(pair, float(count), price)
            print(order)

        except InvalidOrder as io:
            print(io)
        except BadSymbol as bs:
            print(bs)
        except Exception as e:
            print(e)


def conservative_trade(exchange, current_value, buys, sells, portfolio, maker_taker):

    portfolio = commons.sell_portfolio(portfolio, sells, exchange)
    num_buys = len(buys)
    usd_value = float(portfolio.get('USDT'))

    price_per_buy = 0.00
    if usd_value >= (num_buys * 1000):
        price_per_buy = 1000.00
    elif usd_value >= (num_buys * 100):
        price_per_buy = 100.00
    elif usd_value >= (num_buys * 10):
        price_per_buy = 10.00
    elif usd_value >= num_buys:
        price_per_buy = 1.00

    usd_value = float(usd_value) - (num_buys * price_per_buy)
    portfolio['USDT'] = int(usd_value)

    for buy in buys:
        try:
            j = json.dumps(exchange.fetchTicker(buy + "/USDT"), indent=4, sort_keys=True)
        except Exception as e:
            print("** FAULTY LOGIC **")
            print(e)
            portfolio[buy] = price_per_buy  # TODO This is faulty logic
        else:
            c = commons.json_to_candle(j)
            portfolio[buy] = price_per_buy / c.c
            print("buy " + str(portfolio[buy]) + " shares of " + buy + " for " + str(price_per_buy))
    return portfolio


def conservative_backtest_trade(buy_prices, current_value, buys, sells, portfolio, maker_taker):
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
    maker_taker = 'maker'
    trade_style = 'conservative'
    prod = 'true'
    if prod == "true":
        commons.go_slack(event, conservative_live_trade)
        commons.go_live(event, conservative_live_trade)
    else:
        commons.go(event, conservative_trade, conservative_backtest_trade, maker_taker, trade_style)


if __name__ == "__main__":
    main('', '')
