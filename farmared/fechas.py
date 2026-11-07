import datetime


def hoy():
    return datetime.date.today()


def a_datetime(d):
    return datetime.datetime(d.year, d.month, d.day)


def desde_iso(texto):
    return datetime.date.fromisoformat(texto) if texto else None


def a_iso(valor):
    return valor.strftime("%Y-%m-%d") if valor is not None else None


def a_entero(d):
    return d.year * 10000 + d.month * 100 + d.day
