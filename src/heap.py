class IndexedMinHeap:
    __slots__ = ("_prio", "_items", "_pos")

    def __init__(self):
        self._prio: list[float] = []
        self._items: list = []
        self._pos: dict = {}

    def __len__(self) -> int:
        return len(self._prio)

    def __bool__(self) -> bool:
        return bool(self._prio)

    def __contains__(self, item) -> bool:
        return item in self._pos

    def priority_of(self, item) -> float:
        return self._prio[self._pos[item]]

    def peek(self):
        if not self._prio:
            raise IndexError("peek from an empty heap")
        return self._items[0], self._prio[0]

    def push(self, item, priority: float) -> None:
        if item in self._pos:
            raise KeyError(f"{item!r} is already in the heap; use decrease_key")
        i = len(self._prio)
        self._prio.append(priority)
        self._items.append(item)
        self._pos[item] = i
        self._sift_up(i)

    def pop(self):
        prio = self._prio
        items = self._items
        if not prio:
            raise IndexError("pop from an empty heap")
        top_item = items[0]
        top_prio = prio[0]
        last_prio = prio.pop()
        last_item = items.pop()
        del self._pos[top_item]
        if prio:
            prio[0] = last_prio
            items[0] = last_item
            self._pos[last_item] = 0
            self._sift_down(0)
        return top_item, top_prio

    def decrease_key(self, item, new_priority: float) -> None:
        i = self._pos[item]
        if new_priority > self._prio[i]:
            raise ValueError("decrease_key cannot increase a priority")
        self._prio[i] = new_priority
        self._sift_up(i)

    def _sift_up(self, i: int) -> None:
        prio = self._prio
        items = self._items
        pos = self._pos
        p = prio[i]
        item = items[i]
        while i > 0:
            parent = (i - 1) >> 1
            if prio[parent] <= p:
                break
            prio[i] = prio[parent]
            moved = items[parent]
            items[i] = moved
            pos[moved] = i
            i = parent
        prio[i] = p
        items[i] = item
        pos[item] = i

    def _sift_down(self, i: int) -> None:
        prio = self._prio
        items = self._items
        pos = self._pos
        n = len(prio)
        p = prio[i]
        item = items[i]
        while True:
            child = 2 * i + 1
            if child >= n:
                break
            right = child + 1
            if right < n and prio[right] < prio[child]:
                child = right
            if prio[child] >= p:
                break
            prio[i] = prio[child]
            moved = items[child]
            items[i] = moved
            pos[moved] = i
            i = child
        prio[i] = p
        items[i] = item
        pos[item] = i


class LazyMinHeap:
    __slots__ = ("_data",)

    def __init__(self):
        self._data: list = []

    def __len__(self) -> int:
        return len(self._data)

    def __bool__(self) -> bool:
        return bool(self._data)

    def peek(self):
        if not self._data:
            raise IndexError("peek from an empty heap")
        priority, item = self._data[0]
        return item, priority

    def push(self, item, priority: float) -> None:
        data = self._data
        entry = (priority, item)
        i = len(data)
        data.append(entry)
        while i > 0:
            parent = (i - 1) >> 1
            if data[parent] <= entry:
                break
            data[i] = data[parent]
            i = parent
        data[i] = entry

    def pop(self):
        data = self._data
        if not data:
            raise IndexError("pop from an empty heap")
        top = data[0]
        last = data.pop()
        n = len(data)
        if n:
            i = 0
            while True:
                child = 2 * i + 1
                if child >= n:
                    break
                right = child + 1
                if right < n and data[right] < data[child]:
                    child = right
                if data[child] >= last:
                    break
                data[i] = data[child]
                i = child
            data[i] = last
        return top[1], top[0]
