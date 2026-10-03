"""Bounded constructive witnesses for exact numeric aggregate realizability.

Each non-enum float binade is a contiguous integer lattice. Once both observed
extrema are reserved, divisibility and interval bounds prove the remaining
count/sum has a realization. Enum histograms avoid subset-sum search entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from .contract import Field, MAX_NUMBER

MAX_BINARY_STRATA = 2147  # zero, two subnormal signs, 2 * [-1022..49]


class MomentError(ValueError):
    """Impossible or incompatible numeric witness; contains no payload."""


def rational(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def read_rational(value: Any) -> Fraction:
    if type(value) is not list or len(value) != 2 or any(type(x) is not int for x in value):
        raise MomentError("invalid rational state")
    numerator, denominator = value
    if (abs(numerator).bit_length() > 1200 or not 0 < denominator <= 2**1074
            or denominator & (denominator - 1)):
        raise MomentError("rational state is outside the dyadic input domain")
    result = Fraction(numerator, denominator)
    if rational(result) != value:
        raise MomentError("noncanonical rational state")
    return result


def power_two(exponent: int) -> Fraction:
    return Fraction(2**exponent) if exponent >= 0 else Fraction(1, 2**-exponent)


def binary_bin(value: Fraction) -> str:
    if not value:
        return "zero"
    absolute = abs(value)
    sign = "p" if value > 0 else "n"
    if absolute < power_two(-1022):
        return f"{sign}:sub"
    exponent = absolute.numerator.bit_length() - absolute.denominator.bit_length()
    if absolute < power_two(exponent):
        exponent -= 1
    return f"{sign}:{exponent}"


def quantum(bin_name: str) -> Fraction:
    if bin_name == "zero":
        return Fraction(1)
    if bin_name in ("p:sub", "n:sub"):
        return power_two(-1074)
    pieces = bin_name.split(":")
    if len(pieces) != 2 or pieces[0] not in ("p", "n"):
        raise MomentError("invalid binary stratum")
    try:
        exponent = int(pieces[1])
    except ValueError as exc:
        raise MomentError("invalid binary stratum") from exc
    if not -1022 <= exponent <= 49 or pieces[1] != str(exponent):
        raise MomentError("invalid binary stratum exponent")
    return power_two(exponent - 52)


def input_candidates(value: Fraction, declaration: Field) -> list[int | float]:
    """Legal JSON primitive representations, including both float zero signs."""
    if abs(value) > MAX_NUMBER:
        return []
    candidates = []
    if value.denominator == 1:
        candidates.append(value.numerator)
    if declaration.type == "number":
        converted = float(value)
        if Fraction(converted) == value:
            candidates.append(converted)
            if not value:
                candidates.append(-0.0)
    return [candidate for candidate in candidates if declaration.check(candidate) is None]


def input_possible(value: Fraction, declaration: Field) -> bool:
    """Can one accepted built-in integer or binary float have this exact value?"""
    return bool(input_candidates(value, declaration))


def check_uniform(count: int, total: Fraction, lo: Fraction, hi: Fraction, step: Fraction) -> None:
    # Within a binade (or the integer domain), every lattice point in [lo,hi]
    # is an accepted primitive. Removing one occurrence of each extremum
    # leaves an integer interval sum, constructible by quotient/remainder.
    if lo > hi or any((value / step).denominator != 1 for value in (total, lo, hi)):
        raise MomentError("aggregate is not on its input lattice")
    if count == 1:
        feasible = lo == hi == total
    else:
        remainder = total - lo - hi
        feasible = (count - 2) * lo <= remainder <= (count - 2) * hi
    if not feasible:
        raise MomentError("aggregate extrema and sum have no lattice realization")


@dataclass
class Stratum:
    count: int
    total: Fraction
    minimum: Fraction
    maximum: Fraction

    def add(self, value: Fraction) -> None:
        self.count += 1
        self.total += value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)


@dataclass
class Moments:
    total: Fraction
    minimum: Fraction
    maximum: Fraction
    kind: str
    frequencies: dict[Fraction, int] = field(default_factory=dict)
    strata: dict[str, Stratum] = field(default_factory=dict)

    @classmethod
    def first(cls, value: int | float, declaration: Field) -> "Moments":
        exact = Fraction(value)
        kind = "enum" if declaration.enum is not None else "integer" if declaration.type == "integer" else "binary"
        result = cls(exact, exact, exact, kind)
        if kind == "enum":
            result.frequencies[exact] = 1
        elif kind == "binary":
            result.strata[binary_bin(exact)] = Stratum(1, exact, exact, exact)
        return result

    def add(self, value: int | float) -> None:
        exact = Fraction(value)
        self.total += exact
        self.minimum = min(self.minimum, exact)
        self.maximum = max(self.maximum, exact)
        if self.kind == "enum":
            self.frequencies[exact] = self.frequencies.get(exact, 0) + 1
        elif self.kind == "binary":
            name = binary_bin(exact)
            if name in self.strata:
                self.strata[name].add(exact)
            else:
                self.strata[name] = Stratum(1, exact, exact, exact)

    def encode(self) -> dict:
        proof = {"kind": self.kind}
        if self.kind == "enum":
            proof["counts"] = [{"value": rational(value), "count": count}
                               for value, count in sorted(self.frequencies.items())]
        elif self.kind == "binary":
            proof["strata"] = [
                {"bin": name, "count": state.count, "sum": rational(state.total),
                 "min": rational(state.minimum), "max": rational(state.maximum)}
                for name, state in sorted(self.strata.items())]
        return {"sum": rational(self.total), "min": rational(self.minimum),
                "max": rational(self.maximum), "proof": proof}


def read_moments(state: Any, count: int, declaration: Field, strata_limit: int) -> Moments:
    if type(state) is not dict or set(state) != {"sum", "min", "max", "proof"}:
        raise MomentError("invalid aggregate state")
    total, lo, hi = (read_rational(state[key]) for key in ("sum", "min", "max"))
    if lo > hi or not input_possible(lo, declaration) or not input_possible(hi, declaration):
        raise MomentError("aggregate extrema violate the accepted field domain")
    proof = state["proof"]
    kind = "enum" if declaration.enum is not None else "integer" if declaration.type == "integer" else "binary"
    if type(proof) is not dict or proof.get("kind") != kind:
        raise MomentError("aggregate witness type mismatch")
    result = Moments(total, lo, hi, kind)
    if kind == "integer":
        if set(proof) != {"kind"}:
            raise MomentError("invalid integer witness")
        check_uniform(count, total, lo, hi, Fraction(1))
        return result
    if kind == "enum":
        if set(proof) != {"kind", "counts"} or type(proof["counts"]) is not list:
            raise MomentError("invalid enum witness")
        allowed = {Fraction(value) for value in declaration.enum}
        if not 1 <= len(proof["counts"]) <= len(allowed):
            raise MomentError("enum witness exceeds declared cardinality")
        for item in proof["counts"]:
            if type(item) is not dict or set(item) != {"value", "count"}:
                raise MomentError("invalid enum frequency")
            value, frequency = read_rational(item["value"]), item["count"]
            if (value not in allowed or value in result.frequencies or not input_possible(value, declaration)
                    or type(frequency) is not int or not 1 <= frequency <= count):
                raise MomentError("invalid enum frequency domain")
            result.frequencies[value] = frequency
        if (sum(result.frequencies.values()) != count
                or sum((value * frequency for value, frequency in result.frequencies.items()), Fraction()) != total
                or min(result.frequencies) != lo or max(result.frequencies) != hi):
            raise MomentError("enum frequencies do not realize aggregate moments")
        return result
    if set(proof) != {"kind", "strata"} or type(proof["strata"]) is not list:
        raise MomentError("invalid binary witness")
    if not 1 <= len(proof["strata"]) <= min(strata_limit, MAX_BINARY_STRATA):
        raise MomentError("binary witness exceeds stratum limit")
    for item in proof["strata"]:
        if type(item) is not dict or set(item) != {"bin", "count", "sum", "min", "max"}:
            raise MomentError("invalid binary stratum state")
        name, frequency = item["bin"], item["count"]
        if type(name) is not str or name in result.strata or type(frequency) is not int or not 1 <= frequency <= count:
            raise MomentError("invalid binary stratum identity or count")
        step = quantum(name)
        subtotal, low, high = (read_rational(item[key]) for key in ("sum", "min", "max"))
        if (not input_possible(low, declaration) or not input_possible(high, declaration)
                or binary_bin(low) != name or binary_bin(high) != name):
            raise MomentError("binary extrema are not members of their stratum")
        check_uniform(frequency, subtotal, low, high, step)
        result.strata[name] = Stratum(frequency, subtotal, low, high)
    if (sum(item.count for item in result.strata.values()) != count
            or sum((item.total for item in result.strata.values()), Fraction()) != total
            or min(item.minimum for item in result.strata.values()) != lo
            or max(item.maximum for item in result.strata.values()) != hi):
        raise MomentError("binary strata do not realize aggregate moments")
    return result
