"""Portable seeded random generator.

mulberry32 is used so the HTML/JavaScript port can reproduce identical draws:

    function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;
      var t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;
      return((t^t>>>14)>>>0)/4294967296;}}

Every derived draw (normal, Poisson, exponential, Rician power) is built from
random() only, with the same algorithm in both languages.
"""
import math

_M = 0xFFFFFFFF


def _imul(a, b):
    return (a * b) & _M


class Rng:
    def __init__(self, seed=12345):
        self.s = seed & _M
        self._spare = None

    def random(self):
        self.s = (self.s + 0x6D2B79F5) & _M
        a = self.s
        t = _imul(a ^ (a >> 15), 1 | a)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & _M) ^ t
        return ((t ^ (t >> 14)) & _M) / 4294967296.0

    def uniform(self, lo, hi):
        return lo + (hi - lo) * self.random()

    def randint(self, n):
        """Integer in [0, n)."""
        return min(int(self.random() * n), n - 1)

    def normal(self, mu=0.0, sigma=1.0):
        """Box-Muller, caching the second variate (same order in JS)."""
        if self._spare is not None:
            z, self._spare = self._spare, None
            return mu + sigma * z
        u1 = self.random()
        while u1 <= 1e-300:
            u1 = self.random()
        u2 = self.random()
        r = math.sqrt(-2.0 * math.log(u1))
        z0 = r * math.cos(2.0 * math.pi * u2)
        self._spare = r * math.sin(2.0 * math.pi * u2)
        return mu + sigma * z0

    def exponential(self, rate):
        return -math.log(1.0 - self.random()) / rate

    def poisson(self, mean):
        """Knuth below 30, rounded normal above (portable, adequate for MC)."""
        if mean <= 0:
            return 0
        if mean < 30:
            limit = math.exp(-mean)
            k, p = 0, self.random()
            while p > limit:
                k += 1
                p *= self.random()
            return k
        return max(0, int(round(self.normal(mean, math.sqrt(mean)))))

    def rician_power(self, k_db):
        """Unit-mean power of a Rician envelope with K-factor k_db (dB).
        k_db = None gives Rayleigh."""
        k = 0.0 if k_db is None else 10 ** (k_db / 10.0)
        s = math.sqrt(k / (k + 1.0))
        sig = math.sqrt(1.0 / (2.0 * (k + 1.0)))
        x = s + sig * self.normal()
        y = sig * self.normal()
        return x * x + y * y
