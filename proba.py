import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone


SYMBOLS = ["XAUUSD"]  # Pon None para ver todos los símbolos
DAYS_BACK = 30


# ==========================
# FORMATO
# ==========================

def fmt_money(value: float) -> str:
    if value > 0:
        return f"+{value:.2f}"
    return f"{value:.2f}"


def fmt_time(timestamp: int) -> str:
    if not timestamp:
        return "-"
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def color_profit(value: float) -> str:
    text = fmt_money(value)
    if value > 0:
        return f"\033[92m{text}\033[0m"
    if value < 0:
        return f"\033[91m{text}\033[0m"
    return text


def position_type_name(position_type: int) -> str:
    if position_type == mt5.POSITION_TYPE_BUY:
        return "BUY"
    if position_type == mt5.POSITION_TYPE_SELL:
        return "SELL"
    return str(position_type)


def deal_type_name(deal_type: int) -> str:
    names = {
        mt5.DEAL_TYPE_BUY: "BUY",
        mt5.DEAL_TYPE_SELL: "SELL",
        mt5.DEAL_TYPE_BALANCE: "BALANCE",
        mt5.DEAL_TYPE_CREDIT: "CREDIT",
        mt5.DEAL_TYPE_CHARGE: "CHARGE",
        mt5.DEAL_TYPE_CORRECTION: "CORRECTION",
        mt5.DEAL_TYPE_BONUS: "BONUS",
        mt5.DEAL_TYPE_COMMISSION: "COMMISSION",
        mt5.DEAL_TYPE_COMMISSION_DAILY: "COMMISSION DAILY",
        mt5.DEAL_TYPE_COMMISSION_MONTHLY: "COMMISSION MONTHLY",
        mt5.DEAL_TYPE_INTEREST: "INTEREST",
        mt5.DEAL_TYPE_BUY_CANCELED: "BUY CANCELED",
        mt5.DEAL_TYPE_SELL_CANCELED: "SELL CANCELED",
    }
    return names.get(deal_type, str(deal_type))


def print_line(char="─", width=140):
    print(char * width)


def print_header(title: str):
    print()
    print_line("═")
    print(f" {title}")
    print_line("═")


# ==========================
# POSICIONES ABIERTAS
# ==========================

def get_open_positions(symbols=None):
    positions = mt5.positions_get()

    if positions is None:
        raise RuntimeError(f"Error obteniendo positions_get: {mt5.last_error()}")

    rows = []

    for p in positions:
        if symbols and p.symbol not in symbols:
            continue

        rows.append(
            {
                "time": fmt_time(p.time),
                "symbol": p.symbol,
                "ticket": p.ticket,
                "type": position_type_name(p.type),
                "volume": float(p.volume),
                "open_price": float(p.price_open),
                "current_price": float(p.price_current),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "profit": float(p.profit),
                "swap": float(p.swap),
                "magic": p.magic,
                "comment": p.comment or "",
            }
        )

    rows.sort(key=lambda x: x["time"], reverse=True)
    return rows


def print_open_positions_table(rows):
    print_header("POSICIONES ABIERTAS")

    if not rows:
        print("No hay posiciones abiertas.")
        return

    headers = [
        "APERTURA",
        "SYMBOL",
        "TICKET",
        "TIPO",
        "VOL",
        "OPEN",
        "CURRENT",
        "SL",
        "TP",
        "PROFIT",
        "SWAP",
        "MAGIC",
        "COMMENT",
    ]

    widths = [20, 10, 14, 7, 7, 12, 12, 12, 12, 14, 10, 10, 24]

    print(" ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print_line("─", sum(widths) + len(widths) - 1)

    total_profit = 0.0
    total_swap = 0.0

    for r in rows:
        total_profit += r["profit"]
        total_swap += r["swap"]

        line = [
            r["time"].ljust(widths[0]),
            r["symbol"].ljust(widths[1]),
            str(r["ticket"]).ljust(widths[2]),
            r["type"].ljust(widths[3]),
            f"{r['volume']:.2f}".ljust(widths[4]),
            f"{r['open_price']:.2f}".ljust(widths[5]),
            f"{r['current_price']:.2f}".ljust(widths[6]),
            f"{r['sl']:.2f}".ljust(widths[7]) if r["sl"] else "-".ljust(widths[7]),
            f"{r['tp']:.2f}".ljust(widths[8]) if r["tp"] else "-".ljust(widths[8]),
            color_profit(r["profit"]).rjust(widths[9] + 9),
            f"{r['swap']:.2f}".ljust(widths[10]),
            str(r["magic"]).ljust(widths[11]),
            r["comment"][:widths[12]].ljust(widths[12]),
        ]

        print(" ".join(line))

    print_line("─", sum(widths) + len(widths) - 1)

    net = total_profit + total_swap

    print()
    print(f"Posiciones abiertas: {len(rows)}")
    print(f"Profit flotante:     {color_profit(total_profit)}")
    print(f"Swap flotante:       {fmt_money(total_swap)}")
    print(f"Resultado flotante:  {color_profit(net)}")


# ==========================
# POSICIONES CERRADAS
# ==========================

def get_closed_position_deals(symbols=None, days_back=30):
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days_back)

    deals = mt5.history_deals_get(date_from, date_to)

    if deals is None:
        raise RuntimeError(f"Error obteniendo history_deals_get: {mt5.last_error()}")

    closed_rows = []

    for d in deals:
        if symbols and d.symbol not in symbols:
            continue

        # Solo deals que cierran posición
        if d.entry not in (
            mt5.DEAL_ENTRY_OUT,
            mt5.DEAL_ENTRY_INOUT,
            mt5.DEAL_ENTRY_OUT_BY,
        ):
            continue

        closed_rows.append(
            {
                "time": fmt_time(d.time),
                "symbol": d.symbol,
                "position_id": d.position_id,
                "type": deal_type_name(d.type),
                "volume": float(d.volume),
                "price": float(d.price),
                "profit": float(d.profit),
                "swap": float(d.swap),
                "commission": float(d.commission),
                "magic": d.magic,
                "comment": d.comment or "",
                "ticket": d.ticket,
                "order": d.order,
            }
        )

    closed_rows.sort(key=lambda x: x["time"], reverse=True)
    return closed_rows


def print_closed_positions_table(rows):
    print_header(f"HISTORIAL DE POSICIONES CERRADAS - ÚLTIMOS {DAYS_BACK} DÍAS")

    if not rows:
        print("No hay posiciones cerradas en el rango indicado.")
        return

    headers = [
        "CIERRE",
        "SYMBOL",
        "POS_ID",
        "TIPO",
        "VOL",
        "PRECIO CIERRE",
        "PROFIT",
        "SWAP",
        "COMISIÓN",
        "MAGIC",
        "COMMENT",
    ]

    widths = [20, 10, 14, 8, 8, 15, 14, 10, 10, 10, 24]

    print(" ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print_line("─", sum(widths) + len(widths) - 1)

    total_profit = 0.0
    total_swap = 0.0
    total_commission = 0.0

    for r in rows:
        total_profit += r["profit"]
        total_swap += r["swap"]
        total_commission += r["commission"]

        line = [
            r["time"].ljust(widths[0]),
            r["symbol"].ljust(widths[1]),
            str(r["position_id"]).ljust(widths[2]),
            r["type"].ljust(widths[3]),
            f"{r['volume']:.2f}".ljust(widths[4]),
            f"{r['price']:.2f}".ljust(widths[5]),
            color_profit(r["profit"]).rjust(widths[6] + 9),
            f"{r['swap']:.2f}".ljust(widths[7]),
            f"{r['commission']:.2f}".ljust(widths[8]),
            str(r["magic"]).ljust(widths[9]),
            r["comment"][:widths[10]].ljust(widths[10]),
        ]

        print(" ".join(line))

    print_line("─", sum(widths) + len(widths) - 1)

    net = total_profit + total_swap + total_commission

    print()
    print(f"Posiciones cerradas: {len(rows)}")
    print(f"Profit cerrado:      {color_profit(total_profit)}")
    print(f"Swap cerrado:        {fmt_money(total_swap)}")
    print(f"Comisión total:      {fmt_money(total_commission)}")
    print(f"Resultado neto:      {color_profit(net)}")


# ==========================
# MAIN
# ==========================

def main():
    if not mt5.initialize():
        print("No se pudo inicializar MT5:", mt5.last_error())
        return

    try:
        print()
        print_line("═")
        print(" TORUM / MT5 - POSICIONES ABIERTAS Y CERRADAS")
        print_line("═")

        if SYMBOLS:
            print(f"Símbolos: {', '.join(SYMBOLS)}")
        else:
            print("Símbolos: TODOS")

        open_positions = get_open_positions(SYMBOLS)
        closed_positions = get_closed_position_deals(SYMBOLS, DAYS_BACK)

        print_open_positions_table(open_positions)
        print_closed_positions_table(closed_positions)

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()