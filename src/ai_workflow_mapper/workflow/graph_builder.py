"""Process Graph Builder — converts a ProcessExtraction into a canonical ProcessGraph."""

import logging

from ai_workflow_mapper.workflow.domain import (
    Actor,
    DecisionPoint,
    GraphEdge,
    GraphNode,
    Handoff,
    ProcessExtraction,
    ProcessGraph,
    Swimlane,
)

_log = logging.getLogger(__name__)


class ProcessGraphBuilder:
    """Build a canonical ProcessGraph from a ProcessExtraction."""

    def build(self, extraction: ProcessExtraction) -> ProcessGraph:
        if not extraction.steps:
            return ProcessGraph()

        decision_step_ids = {dp.step_id for dp in extraction.decision_points}

        # Sort steps by sequence_order when present, else preserve list order.
        ordered_steps = sorted(
            extraction.steps,
            key=lambda s: (s.sequence_order is None, s.sequence_order or 0),
        )

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # Start node
        start_id = "__start__"
        nodes.append(GraphNode(id=start_id, type="start", label="Start"))

        # One node per step
        for step in ordered_steps:
            node_type = "decision" if step.id in decision_step_ids else "task"
            nodes.append(
                GraphNode(
                    id=step.id,
                    type=node_type,
                    label=step.label,
                    actor_id=_actor_id(step.actor) if step.actor else None,
                    tool=step.tool,
                    duration=step.duration,
                    frequency=step.frequency,
                    metadata={"uncertain": True} if step.uncertain else None,
                )
            )

        # End node
        end_id = "__end__"
        nodes.append(GraphNode(id=end_id, type="end", label="End"))

        # Sequential edges: start → step[0] → step[1] → ... → end
        # Handoffs override the direct edge between their two steps.
        handoff_pairs: set[tuple[str, str]] = {
            (h.from_step_id, h.to_step_id) for h in extraction.handoffs
        }

        step_ids = [s.id for s in ordered_steps]

        edges.append(GraphEdge(**{"from": start_id, "to": step_ids[0]}))
        for i in range(len(step_ids) - 1):
            src, dst = step_ids[i], step_ids[i + 1]
            if (src, dst) not in handoff_pairs:
                edges.append(GraphEdge(**{"from": src, "to": dst}))
        edges.append(GraphEdge(**{"from": step_ids[-1], "to": end_id}))

        # Handoff nodes + edges
        for idx, h in enumerate(extraction.handoffs):
            handoff_node_id = f"__handoff_{idx}__"
            label = (
                f"{h.from_actor or h.from_step_id} → {h.to_actor or h.to_step_id}"
            )
            nodes.append(GraphNode(id=handoff_node_id, type="handoff", label=label))
            edges.append(GraphEdge(**{"from": h.from_step_id, "to": handoff_node_id}))
            edges.append(GraphEdge(**{"from": handoff_node_id, "to": h.to_step_id}))

        # Decision point branch edges
        for dp in extraction.decision_points:
            if dp.true_branch_step_id:
                edges.append(
                    GraphEdge(
                        **{"from": dp.step_id, "to": dp.true_branch_step_id},
                        label=f"Yes: {dp.condition}",
                    )
                )
            if dp.false_branch_step_id:
                edges.append(
                    GraphEdge(
                        **{"from": dp.step_id, "to": dp.false_branch_step_id},
                        label=f"No: {dp.condition}",
                    )
                )

        # Actors (deduplicated)
        seen_actor_names: dict[str, str] = {}  # name → id
        for step in ordered_steps:
            if step.actor and step.actor not in seen_actor_names:
                actor_id = _actor_id(step.actor)
                seen_actor_names[step.actor] = actor_id
        # Also include actors mentioned in handoffs
        for h in extraction.handoffs:
            for name in [h.from_actor, h.to_actor]:
                if name and name not in seen_actor_names:
                    seen_actor_names[name] = _actor_id(name)

        actors = [
            Actor(id=actor_id, name=name, kind="role")
            for name, actor_id in seen_actor_names.items()
        ]

        # Swimlanes: group node ids by actor_id
        actor_to_nodes: dict[str, list[str]] = {a.id: [] for a in actors}
        for node in nodes:
            if node.actor_id and node.actor_id in actor_to_nodes:
                actor_to_nodes[node.actor_id].append(node.id)

        swimlanes = [
            Swimlane(actor_id=actor_id, node_ids=node_ids)
            for actor_id, node_ids in actor_to_nodes.items()
            if node_ids
        ]

        _log.info(
            "ProcessGraph built: %d nodes, %d edges, %d actors",
            len(nodes),
            len(edges),
            len(actors),
        )

        return ProcessGraph(
            nodes=nodes,
            edges=edges,
            actors=actors,
            swimlanes=swimlanes,
        )


def _actor_id(name: str) -> str:
    """Stable slug from an actor name."""
    return name.lower().replace(" ", "_").replace("-", "_")
