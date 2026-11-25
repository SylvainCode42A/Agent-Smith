import time
from smith_core.models import StepMetrics
from smith_core.agent.loop import Limits, budget_left


def mk(i, inp, out=250, ms=0):
    return StepMetrics(step=i, input_tokens=inp, output_tokens=out,
                       request_time_ms=ms)


limits = Limits()
start = time.monotonic() - 100

assert budget_left([mk(1, 100, ms=5000)], limits, start) is True

assert budget_left([mk(1, 100, ms=25000)], limits, start) is False

steps = [mk(1, 100, ms=1000), mk(2, 100, ms=25000), mk(3, 100, ms=1000)]
assert budget_left(steps, limits, start) is False

assert budget_left([], limits, start) is True

print("time anticipation OK")
