import MetaTrader5 as mt5

mt5.initialize()


for s in ["XAUUSD"]:
    info = mt5.symbol_info(s)
    tick = mt5.symbol_info_tick(s)
    
    print("tick:", tick)

mt5.shutdown()