"""Job source adapters. Every source implements JobSource; core code never knows source specifics."""
from abc import ABC, abstractmethod

from app.schemas import RawJob


class JobSource(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, query: str | None, location: str | None, limit: int) -> list[RawJob]:
        """Return real postings from the source. Raise JobSourceError on failure."""
