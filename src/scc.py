import numpy as np


def strongly_connected_components(offsets: list[int], targets: list[int]) -> list[int]:
    n = len(offsets) - 1
    index_of = [-1] * n
    low = [0] * n
    on_stack = [False] * n
    comp = [-1] * n
    stack: list[int] = []
    counter = 0
    n_comp = 0
    for root in range(n):
        if index_of[root] != -1:
            continue
        work = [(root, offsets[root])]
        index_of[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        while work:
            u, pos = work[-1]
            if pos < offsets[u + 1]:
                work[-1] = (u, pos + 1)
                v = targets[pos]
                if index_of[v] == -1:
                    index_of[v] = low[v] = counter
                    counter += 1
                    stack.append(v)
                    on_stack[v] = True
                    work.append((v, offsets[v]))
                elif on_stack[v] and index_of[v] < low[u]:
                    low[u] = index_of[v]
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    if low[u] < low[parent]:
                        low[parent] = low[u]
                if low[u] == index_of[u]:
                    while True:
                        w = stack.pop()
                        on_stack[w] = False
                        comp[w] = n_comp
                        if w == u:
                            break
                    n_comp += 1
    return comp


def largest_scc_mask(graph) -> np.ndarray:
    comp = strongly_connected_components(graph.offsets.tolist(), graph.targets.tolist())
    labels = np.array(comp, dtype=np.int64)
    sizes = np.bincount(labels)
    return labels == int(np.argmax(sizes))
