from decimal import Decimal
import statistics


def mad_score(values: list[Decimal]) -> list[Decimal]:
    """Median Absolute Deviation score per point in a series."""
    if len(values) < 3:
        return [Decimal("0")] * len(values)
    median = statistics.median(values)
    abs_devs = [abs(v - median) for v in values]
    mad = statistics.median(abs_devs)
    if mad == 0:
        return [Decimal("0")] * len(values)
    # 0.6745 scales MAD to be comparable to a standard deviation under normality
    return [Decimal("0.6745") * abs(v - median) / mad for v in values]
 

def _sustained_flags(values: list[Decimal], persistence_periods: int, median: Decimal) -> list[bool]:
    """
    Returns a boolean per index: True if that index falls inside a run of
    `persistence_periods` or more CONSECUTIVE elevated periods (elevated =
    >= 1.5x median).
 
    This replaces a per-index forward-only window check, which incorrectly
    judged sustained-ness independently at each index rather than by
    membership in a run. A forward window starting mid-run can slide past
    the end of the elevated block and see a false "not sustained" result
    for points that are, in fact, part of the same sustained run — e.g. a
    3-period elevated run at indices 4-6 would correctly mark index 4 as
    sustained (window [4:7] is all elevated) but incorrectly mark index 5
    as NOT sustained (window [5:8] rolls in the first normal value at 7,
    even though index 5 is still inside the same run).
    """
    threshold = median * Decimal("1.5")
    n = len(values)
    elevated = [v >= threshold for v in values]
    sustained = [False] * n
 
    i = 0
    while i < n:
        if elevated[i]:
            j = i
            while j < n and elevated[j]:
                j += 1
            run_length = j - i
            if run_length >= persistence_periods:
                for k in range(i, j):
                    sustained[k] = True
            i = j
        else:
            i += 1
 
    return sustained
 
 


def detect_candidates(
    series_values: list[Decimal],
    mad_threshold: Decimal,
    persistence_periods: int,
    min_history_periods: int,
) -> list[int]:
    """
    Returns list of indices in series_values flagged as outlier candidates.
    series_values must be in chronological order.
    """
    if len(series_values) < min_history_periods:
        return []
 
    scores = mad_score(series_values)
    median = Decimal(str(statistics.median(series_values)))
    sustained = _sustained_flags(series_values, persistence_periods, median)
 
    candidates = []
    for i, score in enumerate(scores):
        if score < mad_threshold:
            continue
        if sustained[i]:
            continue  # part of a sustained elevated run -> level shift, not a candidate
        candidates.append(i)
    return candidates
 
