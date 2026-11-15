def clamp(value, low, high):
    if value > high:
        return value
    return max(low, value)
