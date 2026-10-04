"""Ordered, bounded scoring across independently qualified GPU backends."""
from concurrent.futures import ThreadPoolExecutor


class OrderedScorers:
    def __init__(self, scorers):
        self.scorers = tuple(scorers)
        if not self.scorers:
            raise ValueError("At least one scorer is required")
        self.pool = (ThreadPoolExecutor(max_workers=len(self.scorers))
                     if len(self.scorers) > 1 else None)

    def score(self, keys):
        if not len(keys):
            return []
        count = min(len(keys), len(self.scorers))
        if self.pool is None:
            return [self.scorers[0](keys)]
        futures = []
        try:
            for index in range(count):
                start = index * len(keys) // count
                end = (index + 1) * len(keys) // count
                futures.append(self.pool.submit(self.scorers[index], keys[start:end]))
            return [future.result() for future in futures]
        finally:
            # Drain every device before returning or propagating the first error.
            # A later batch must never reuse a backend still processing this one.
            for future in futures:
                try:
                    future.result()
                except BaseException:
                    pass

    def close(self):
        if self.pool:
            self.pool.shutdown(wait=True)
