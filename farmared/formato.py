import datetime


def a_json(obj):
    if isinstance(obj, dict):
        return {k: a_json(v) for k, v in obj.items() if k != "_id"}
    if isinstance(obj, list):
        return [a_json(v) for v in obj]
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.strftime("%Y-%m-%d")
    return obj
