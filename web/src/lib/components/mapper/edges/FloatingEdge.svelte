<script lang="ts">
  import { BaseEdge, useNodes, type EdgeProps } from "@xyflow/svelte";
  import { getEdgeParams, createBezierPath } from "./floatingEdgeUtils";

  type $$Props = EdgeProps;

  export let id: $$Props["id"];
  export let source: $$Props["source"];
  export let target: $$Props["target"];
  export let markerEnd: $$Props["markerEnd"] = undefined;
  export let style: $$Props["style"] = undefined;
  export let selected: $$Props["selected"] = false;

  const nodes = useNodes();

  $: sourceNode = $nodes.find((n) => n.id === source);
  $: targetNode = $nodes.find((n) => n.id === target);

  $: edgeParams =
    sourceNode && targetNode ? getEdgeParams(sourceNode, targetNode) : null;

  $: path = edgeParams ? createBezierPath(edgeParams) : "";
</script>

{#if edgeParams}
  <BaseEdge {id} path={path} {markerEnd} {style} class={selected ? "selected" : ""} />
{/if}
