import re

_INDEX = re.compile(r"([^\[\]]+)|\[(\d+)\]")


def dig(value: object, dotted: str) -> object:
    for part in dotted.split("."):
        for key, index in _INDEX.findall(part):
            if key:
                if not isinstance(value, dict) or key not in value:
                    return None
                value = value[key]
            else:
                if not isinstance(value, list) or int(index) >= len(value):
                    return None
                value = value[int(index)]
    return value
