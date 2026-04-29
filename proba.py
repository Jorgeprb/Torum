import MetaTrader5 as mt5
from datetime import datetime

SYMBOLS = ["XAUUSD"]  # Pon None para ver todas


def money(x):
    return f"{x:+.2f}"


def time_str(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def side_name(t):
    return "BUY" if t == mt5.POSITION_TYPE_BUY else "SELL"


def main():
    if not mt5.initialize():
        print("No se pudo inicializar MT5:", mt5.last_error())
        return

    try:
        positions = mt5.positions_get()
        if positions is None:
            print("Error obteniendo posiciones:", mt5.last_error())
            return

        if SYMBOLS:
            positions = [p for p in positions if p.symbol in SYMBOLS]

        print("\nOPERACIONES ABIERTAS\n")
        print(f"{'FECHA':19} {'SYMBOL':8} {'TIPO':5} {'VOL':>6} {'OPEN':>10} {'ACTUAL':>10} {'PROFIT':>10} {'SWAP':>8} {'NETO':>10}")
        print("-" * 100)

        total_profit = total_swap = total_net = 0.0

        for p in positions:
            profit = float(p.profit)
            swap = float(p.swap)
            net = profit + swap

            total_profit += profit
            total_swap += swap
            total_net += net

            print(
                f"{time_str(p.time):19} "
                f"{p.symbol:8} "
                f"{side_name(p.type):5} "
                f"{p.volume:6.2f} "
                f"{p.price_open:10.2f} "
                f"{p.price_current:10.2f} "
                f"{money(profit):>10} "
                f"{money(swap):>8} "
                f"{money(net):>10}"
            )

        print("-" * 100)
        print(f"{'TOTAL':63} {money(total_profit):>10} {money(total_swap):>8} {money(total_net):>10}")

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()