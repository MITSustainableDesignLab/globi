import { writable } from "svelte/store";

export type WorkflowMode = "workflow1" | "workflow2" | null;

export const workflowMode = writable<WorkflowMode>(null);
