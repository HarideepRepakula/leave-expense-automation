"""Seeded, independent RNG streams (amendment A8, docs/07 section 4).

One master seed -> numpy SeedSequence -> one child per named stream, in a fixed order. A stream's draws depend
only on its own child seed, so changing the volume of one stage cannot reshuffle another stage's draws.
No code in src/ may use the Python `random` module.

Keyed draws (Phase 7B): keyed_integers() draws from a child of a stream's seed identified by a record key (for
example request id, round and level), so a delay depends only on its key and never on the order in which a
simulation asks for it (ASM-P7B-02). The child seed is SeedSequence(stream entropy, stream spawn_key + key words),
key words = the first 8 bytes of SHA-256 of each key part, big-endian.
"""
from __future__ import annotations

import hashlib

import numpy as np
from faker import Faker

FAKER_LOCALES = {"IN": "en_IN", "US": "en_US", "GB": "en_GB"}


class RngStreams:
    def __init__(self, master_seed: int, names: list[str]) -> None:
        if len(set(names)) != len(names):
            raise ValueError("stream names must be unique")
        children = np.random.SeedSequence(master_seed).spawn(len(names))
        self._seeds = dict(zip(names, children))
        self._generators: dict[str, np.random.Generator] = {}

    def get(self, name: str) -> np.random.Generator:
        """Return the stream's Generator (PCG64). Repeated calls return the same object, so draws continue."""
        if name not in self._seeds:
            raise KeyError(f"unknown RNG stream '{name}'")
        if name not in self._generators:
            self._generators[name] = np.random.Generator(np.random.PCG64(self._seeds[name]))
        return self._generators[name]

    def keyed_integers(self, name: str, key: tuple, low: int, high: int) -> int:
        """One integer in [low, high] (both inclusive) for this key, independent of every other draw."""
        if name not in self._seeds:
            raise KeyError(f"unknown RNG stream '{name}'")
        parent = self._seeds[name]
        words = tuple(int.from_bytes(hashlib.sha256(str(part).encode()).digest()[:8], "big") for part in key)
        child = np.random.SeedSequence(parent.entropy, spawn_key=tuple(parent.spawn_key) + words,
                                       pool_size=parent.pool_size)
        return int(np.random.Generator(np.random.PCG64(child)).integers(low, high + 1))

    def fakers(self, name: str) -> dict[str, Faker]:
        """One Faker per country locale, each seeded from the named stream (fixed locale order)."""
        gen = self.get(name)
        result = {}
        for country, locale in FAKER_LOCALES.items():
            fake = Faker(locale)
            fake.seed_instance(int(gen.integers(0, 2**31 - 1)))
            result[country] = fake
        return result
