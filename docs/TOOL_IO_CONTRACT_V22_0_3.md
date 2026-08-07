# V22.0.3 Tool IO Contract & Slot Transport

## Goal

Keep the existing two-level planning boundary:

```text
MainAgent -> Worker DAG
Worker -> Private Tool DAG
Runtime -> deterministic Tool-to-Tool transport
```

A Worker decides **which Tool to use and in what dependency order**. Runtime does not decide the business sequence. Runtime only guarantees that semantic Tool inputs/outputs are moved and validated consistently.

## Tool IO Contract v1

Each migrated Tool may declare:

- `ToolInputContract`: semantic input slot, schema id, required flag, accepted source classes.
- `ToolOutputContract`: semantic output slot, schema id, Runtime-only `source_path`, provenance policy.

Example:

```text
internal.ranking.get_latest
  output: market_ranking_signals : RankingSignals.v1

internal.entity.resolve_ranked_security
  input : market_ranking_signals : RankingSignals.v1
  output: selected_entity_ref    : GraphRef.v1
  output: security_node_id       : SecurityNodeId.v1

internal.prediction.get_stock
  input : security_node_id       : SecurityNodeId.v1
  output: entity_model_signals   : EntityModelSignals.v1
```

## Planner visibility

Worker sees semantic contracts only. It does **not** see Runtime extraction paths such as:

```text
data.records
data.record
data.metrics
```

Therefore a Tool DAG references semantic outputs:

```json
{
  "from_tool_task_id": "task_get_ranking",
  "output_slot": "market_ranking_signals"
}
```

not Python return fields such as `data_key=records`.

## Runtime transport

After Tool execution, Runtime maps concrete return values into standard semantic slots:

```text
Tool raw result
  -> Tool Output Adapter
  -> result.data.slots[semantic_slot]
  -> Tool DAG input binding
  -> downstream Tool argument
```

For example:

```text
data.records
  -> market_ranking_signals
  -> resolve_ranked_security
```

The `source_path` mapping is Runtime-private and is omitted from Worker/public views.

## Local Replan

Successful Tool nodes are frozen. A local Replan may reference their semantic output slots without re-executing them:

```text
frozen ranking result
   -> output_slot: market_ranking_signals
   -> new resolver node
   -> new prediction node
```

Validator treats frozen successful Tool task ids as externally satisfied DAG roots. Executor accepts frozen final outputs when evaluating the repaired DAG.

## Compatibility

V22.0.3 is incremental:

- migrated Tools use Tool IO Contract v1;
- legacy Tools keep the previous `produced_outputs` / raw-result behavior;
- contracted Tools cannot use raw `data_key` for Tool-to-Tool binding;
- no MainAgent Worker-selection or upfront Worker-DAG semantics are changed.

## W02 first migration

The ranking -> entity resolution -> prediction chain is the first explicit migration because it exposed the concrete failure in `agent_run_2af309b97876`.
