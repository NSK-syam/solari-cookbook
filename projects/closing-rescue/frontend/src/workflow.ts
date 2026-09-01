import type { ClosingRescueView } from "./api";

export type WorkflowPhase = "pending" | "approved" | "authorized" | "running" | "finalization_pending" | "failed" | "unknown" | "rejected" | "completed" | "consumed" | "not_required";

export function workflowLifecycle(view: ClosingRescueView): { phase: WorkflowPhase; retainToken: boolean; resumable: boolean } {
  const approval = view.approval;
  const action = view.actions.at(-1);
  let phase: WorkflowPhase;
  if (view.story_events.some((event) => event.event_type === "rescue.completed")) phase = "completed";
  else if (approval?.state === "rejected") phase = "rejected";
  else if (action?.state === "failed") phase = "failed";
  else if (action?.state === "unknown") phase = "unknown";
  else if (action?.state === "succeeded") phase = "finalization_pending";
  else if (action?.state === "running") phase = "running";
  else if (action?.state === "authorized") phase = "authorized";
  else if (approval?.state === "pending") phase = "pending";
  else if (approval?.state === "approved") phase = "approved";
  else if (approval?.state === "not_required") phase = "not_required";
  else phase = "consumed";
  const resumable = ["pending", "approved", "authorized", "running", "finalization_pending"].includes(phase);
  return { phase, retainToken: resumable, resumable };
}
