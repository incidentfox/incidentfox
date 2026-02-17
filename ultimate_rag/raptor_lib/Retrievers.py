from abc import ABC, abstractmethod


class BaseRetriever(ABC):
    @abstractmethod
    def retrieve(self, query: str) -> str:
        pass
