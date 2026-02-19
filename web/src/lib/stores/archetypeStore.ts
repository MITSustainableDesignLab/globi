import { writable } from "svelte/store";
import type {
  Distribution,
  SemanticField,
  SemanticFieldCondition
} from "$lib/types/mapper";
import { buildComponentLevels, buildInitialFields } from "$lib/data/mapperSeed";

export type ArchetypeDistribution = {
  componentPath: string;
  type: "range" | "fixed";
  min?: number;
  max?: number;
  value?: number;
};

export type ComponentValueDefinition = {
  componentPath: string;
  parameterName: string;
  value?: number;
  distribution?: Distribution;
  conditions?: SemanticFieldCondition;
};

export type ArchetypeIcon = "building" | "tower" | "warehouse";

export type Archetype = {
  id: string;
  name: string;
  description?: string;
  icon: ArchetypeIcon;
  distributions: Record<string, ArchetypeDistribution>;
  componentValues?: ComponentValueDefinition[];
  linkedConditions?: SemanticFieldCondition;
};

export type ArchetypeState = {
  semanticFields: SemanticField[];
  componentPaths: string[];
  archetypes: Archetype[];
  links: Record<string, string[]>;
  selectedArchetypeId: string | null;
};

const toArchetypeId = (name: string) =>
  `archetype_${name.toLowerCase().replace(/[^a-z0-9]+/g, "_")}`;

const componentPaths = buildComponentLevels().map((level) => level.path);

const createDistributions = () =>
  Object.fromEntries(
    componentPaths.map((path) => [
      path,
      { componentPath: path, type: "range", min: 0, max: 0 }
    ])
  );

const baseArchetypes: Archetype[] = [
  {
    id: toArchetypeId("baseline"),
    name: "baseline",
    description: "default building archetype",
    icon: "building",
    distributions: createDistributions()
  }
];

export const archetypeStore = writable<ArchetypeState>({
  semanticFields: buildInitialFields(),
  componentPaths,
  archetypes: baseArchetypes,
  links: {
    [baseArchetypes[0].id]: []
  },
  selectedArchetypeId: baseArchetypes[0].id
});

export const addArchetype = (name: string, icon: ArchetypeIcon): string | null => {
  let newId: string | null = null;
  archetypeStore.update((state) => {
    const trimmed = name.trim();
    if (!trimmed) {
      return state;
    }
    const exists = state.archetypes.some(
      (archetype) => archetype.name.toLowerCase() === trimmed.toLowerCase()
    );
    if (exists) {
      return state;
    }
    const newArchetype: Archetype = {
      id: toArchetypeId(trimmed),
      name: trimmed,
      icon,
      distributions: createDistributions()
    };
    newId = newArchetype.id;
    return {
      ...state,
      archetypes: [...state.archetypes, newArchetype],
      links: { ...state.links, [newArchetype.id]: [] },
      selectedArchetypeId: newArchetype.id
    };
  });
  return newId;
};

export const selectArchetype = (archetypeId: string) => {
  archetypeStore.update((state) => ({
    ...state,
    selectedArchetypeId: archetypeId
  }));
};

export const updateArchetypeIcon = (
  archetypeId: string,
  icon: ArchetypeIcon
) => {
  archetypeStore.update((state) => ({
    ...state,
    archetypes: state.archetypes.map((item) =>
      item.id === archetypeId ? { ...item, icon } : item
    )
  }));
};

export const toggleArchetypeLink = (archetypeId: string, fieldId: string) => {
  archetypeStore.update((state) => {
    const current = state.links[archetypeId] ?? [];
    const exists = current.includes(fieldId);
    const next = exists
      ? current.filter((id) => id !== fieldId)
      : [...current, fieldId];
    return {
      ...state,
      links: { ...state.links, [archetypeId]: next }
    };
  });
};

export const addArchetypeLink = (archetypeId: string, fieldId: string) => {
  archetypeStore.update((state) => {
    const current = state.links[archetypeId] ?? [];
    if (current.includes(fieldId)) {
      return state;
    }
    return {
      ...state,
      links: { ...state.links, [archetypeId]: [...current, fieldId] }
    };
  });
};

export const removeArchetypeLink = (archetypeId: string, fieldId: string) => {
  archetypeStore.update((state) => {
    const current = state.links[archetypeId] ?? [];
    if (!current.includes(fieldId)) {
      return state;
    }
    return {
      ...state,
      links: { ...state.links, [archetypeId]: current.filter((id) => id !== fieldId) }
    };
  });
};

export const updateArchetypeDistribution = (
  archetypeId: string,
  componentPath: string,
  update: Partial<ArchetypeDistribution>
) => {
  archetypeStore.update((state) => {
    const archetype = state.archetypes.find((item) => item.id === archetypeId);
    if (!archetype) {
      return state;
    }
    const current = archetype.distributions[componentPath];
    if (!current) {
      return state;
    }
    const nextDistribution = { ...current, ...update };
    const updated = state.archetypes.map((item) =>
      item.id === archetypeId
        ? {
            ...item,
            distributions: {
              ...item.distributions,
              [componentPath]: nextDistribution
            }
          }
        : item
    );
    return { ...state, archetypes: updated };
  });
};

export const setArchetypeComponentValues = (
  archetypeId: string,
  componentValues: ComponentValueDefinition[]
) => {
  archetypeStore.update((state) => ({
    ...state,
    archetypes: state.archetypes.map((item) =>
      item.id === archetypeId ? { ...item, componentValues } : item
    )
  }));
};

export const setArchetypeLinkedConditions = (
  archetypeId: string,
  conditions: SemanticFieldCondition
) => {
  archetypeStore.update((state) => ({
    ...state,
    archetypes: state.archetypes.map((item) =>
      item.id === archetypeId ? { ...item, linkedConditions: conditions } : item
    )
  }));
};
