def first_nonempty(values, default):
    for value in values:
        if value:
            return value
    return None
