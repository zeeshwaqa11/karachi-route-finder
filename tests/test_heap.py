import heapq

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.heap import IndexedMinHeap, LazyMinHeap

priorities = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)


def test_indexed_heap_basic_order():
    h = IndexedMinHeap()
    for item, p in [("a", 5.0), ("b", 1.0), ("c", 3.0)]:
        h.push(item, p)
    assert len(h) == 3
    assert h.peek() == ("b", 1.0)
    h.decrease_key("a", 0.5)
    assert [h.pop()[0] for _ in range(3)] == ["a", "b", "c"]
    assert not h


def test_indexed_heap_errors():
    h = IndexedMinHeap()
    with pytest.raises(IndexError):
        h.pop()
    with pytest.raises(IndexError):
        h.peek()
    h.push(1, 2.0)
    with pytest.raises(KeyError):
        h.push(1, 1.0)
    with pytest.raises(ValueError):
        h.decrease_key(1, 3.0)
    with pytest.raises(KeyError):
        h.decrease_key(99, 1.0)


def test_lazy_heap_allows_duplicates_and_orders_them():
    h = LazyMinHeap()
    h.push("x", 4.0)
    h.push("x", 2.0)
    h.push("y", 3.0)
    assert len(h) == 3
    assert h.pop() == ("x", 2.0)
    assert h.pop() == ("y", 3.0)
    assert h.pop() == ("x", 4.0)
    with pytest.raises(IndexError):
        h.pop()


operation = st.one_of(
    st.tuples(st.just("push"), st.integers(0, 40), priorities),
    st.tuples(st.just("pop"), st.just(0), st.just(0.0)),
    st.tuples(st.just("decrease"), st.integers(0, 40), priorities),
    st.tuples(st.just("peek"), st.just(0), st.just(0.0)),
)


@settings(max_examples=300, deadline=None)
@given(st.lists(operation, max_size=200))
def test_indexed_heap_matches_reference_model(ops):
    heap = IndexedMinHeap()
    model: dict[int, float] = {}
    for kind, item, p in ops:
        if kind == "push":
            if item in model:
                with pytest.raises(KeyError):
                    heap.push(item, p)
            else:
                heap.push(item, p)
                model[item] = p
        elif kind == "decrease":
            if item not in model:
                with pytest.raises(KeyError):
                    heap.decrease_key(item, p)
            elif p > model[item]:
                with pytest.raises(ValueError):
                    heap.decrease_key(item, p)
            else:
                heap.decrease_key(item, p)
                model[item] = p
        elif kind == "peek":
            if model:
                assert heap.peek()[1] == min(model.values())
            else:
                with pytest.raises(IndexError):
                    heap.peek()
        else:
            if model:
                got_item, got_p = heap.pop()
                assert got_p == min(model.values())
                assert model.pop(got_item) == got_p
            else:
                with pytest.raises(IndexError):
                    heap.pop()
        assert len(heap) == len(model)
        assert all(heap.priority_of(k) == v for k, v in model.items())


@settings(max_examples=300, deadline=None)
@given(
    st.lists(
        st.one_of(
            st.tuples(st.just("push"), st.integers(0, 20), priorities), st.tuples(st.just("pop"), st.just(0), st.just(0.0))
        ),
        max_size=300,
    )
)
def test_lazy_heap_matches_heapq(ops):
    ours = LazyMinHeap()
    ref: list = []
    for kind, item, p in ops:
        if kind == "push":
            ours.push(item, p)
            heapq.heappush(ref, (p, item))
        elif ref:
            expected_p, expected_item = heapq.heappop(ref)
            got_item, got_p = ours.pop()
            assert (got_p, got_item) == (expected_p, expected_item)
        else:
            with pytest.raises(IndexError):
                ours.pop()
        assert len(ours) == len(ref)
        if ref:
            assert (ours.peek()[1], ours.peek()[0]) == ref[0]


@settings(max_examples=200, deadline=None)
@given(st.lists(priorities, max_size=200))
def test_heapsort_property(values):
    lazy = LazyMinHeap()
    indexed = IndexedMinHeap()
    for i, v in enumerate(values):
        lazy.push(i, v)
        indexed.push(i, v)
    expected = sorted(values)
    assert [lazy.pop()[1] for _ in values] == expected
    assert [indexed.pop()[1] for _ in values] == expected
