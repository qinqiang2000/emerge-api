"""Document-matching engine (一锚多源核对).

`judge.py` — per key-pair tolerance comparison (L1) + an LLM tie-breaker (L2);
`engine.py` — full candidate scoring + greedy 1:1 assignment per source.

Both operate purely on extract RESULTS (field values from
`predictions/_draft`). No bbox, no document body, no coordinates ever enter a
prompt (hard rule).
"""
