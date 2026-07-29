def prefix_sum(values):
    output = [0] * len(values)
    for i, value in enumerate(values):
        if i == 0:
            output[i] = value
        else:
            output[i] = output[i - 1] + value
    return output

