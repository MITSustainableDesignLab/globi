import type {
  ComponentLevel,
  DerivedFieldType,
  RangeMapping,
  SemanticField
} from "$lib/types/mapper";
import { PRISMA_COMPONENTS } from "$lib/data/prismaComponents";

const baseSemanticFields: SemanticField[] = [
  {
    id: "field_region",
    name: "Region",
    type: "categorical",
    options: ["north", "south", "east", "west"],
    color: "#4f46e5",
    isDerived: false
  },
  {
    id: "field_typology",
    name: "Typology",
    type: "categorical",
    options: ["office", "retail", "hotel", "warehouse", "school", "hospital"],
    color: "#0ea5e9",
    isDerived: false
  },
  {
    id: "field_age",
    name: "Age_bracket",
    type: "categorical",
    options: ["pre_1980", "1980_1999", "2000_2009", "2010_2019", "2020_plus"],
    color: "#16a34a",
    isDerived: false
  },
  {
    id: "field_weather",
    name: "Weatherization",
    type: "categorical",
    options: ["low", "medium", "high", "retrofit"],
    color: "#f97316",
    isDerived: false
  },
  {
    id: "field_floor_area",
    name: "Floor_area",
    type: "numeric",
    options: [],
    color: "#9333ea",
    isDerived: false
  }
];

const derivedRangeMapping: RangeMapping[] = [
  { min: 0, max: 10000, label: "small" },
  { min: 10001, max: 50000, label: "medium" },
  { min: 50001, max: 200000, label: "large" }
];

const derivedSemanticFields: SemanticField[] = [
  {
    id: "field_age_group",
    name: "Age_group",
    type: "categorical",
    options: ["legacy", "modern"],
    color: "#db2777",
    isDerived: true,
    sourceFieldId: "field_age",
    derivedType: "categorical_mapping",
    groupMapping: {
      legacy: ["pre_1980", "1980_1999"],
      modern: ["2000_2009", "2010_2019", "2020_plus"]
    }
  },
  {
    id: "field_size_band",
    name: "Size_band",
    type: "categorical",
    options: ["small", "medium", "large", "other"],
    color: "#22c55e",
    isDerived: true,
    sourceFieldId: "field_floor_area",
    derivedType: "numeric_range",
    rangeMapping: derivedRangeMapping
  }
];

const componentPalette = [
  "#2563eb",
  "#7c3aed",
  "#db2777",
  "#16a34a",
  "#0ea5e9",
  "#f97316"
];

const hexToRgb = (hex: string) => {
  const cleaned = hex.replace("#", "");
  const value = cleaned.length === 3
    ? cleaned
        .split("")
        .map((char) => char + char)
        .join("")
    : cleaned;
  const intValue = Number.parseInt(value, 16);
  return {
    r: (intValue >> 16) & 255,
    g: (intValue >> 8) & 255,
    b: intValue & 255
  };
};

const rgbToHex = (r: number, g: number, b: number) =>
  `#${[r, g, b]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("")}`;

const lightenHex = (hex: string, amount: number) => {
  const { r, g, b } = hexToRgb(hex);
  const mix = (value: number) =>
    Math.round(value + (255 - value) * Math.min(Math.max(amount, 0), 1));
  return rgbToHex(mix(r), mix(g), mix(b));
};

const getComponentBaseColor = (path: string) => {
  if (path.startsWith("Envelope")) {
    return "#15803d";
  }
  if (path.startsWith("Operations.HVAC")) {
    return "#2563eb";
  }
  if (path.startsWith("Operations.SpaceUse")) {
    return "#7c3aed";
  }
  return "#6b7280";
};

const toComponentId = (path: string) =>
  `component_${path.toLowerCase().replace(/[^a-z0-9]+/g, "_")}`;

const walkComponents = (
  name: string,
  depth: number,
  parentPath: string | null,
  levels: ComponentLevel[]
) => {
  const info = PRISMA_COMPONENTS[name];
  if (!info) {
    return;
  }
  const path = parentPath ? `${parentPath}.${name}` : name;
  const baseColor = getComponentBaseColor(path);
  const color = lightenHex(baseColor, Math.min(depth * 0.12, 0.45));
  levels.push({
    id: toComponentId(path),
    name,
    displayName: info.displayName,
    path,
    depth,
    description: info.description,
    color
  });
  info.children.forEach((child) => walkComponents(child, depth + 1, path, levels));
};

export const buildComponentLevels = (): ComponentLevel[] => {
  const levels: ComponentLevel[] = [];
  walkComponents("Envelope", 0, null, levels);
  walkComponents("Operations", 0, null, levels);
  return levels;
};

const fieldLinks: Record<string, string[]> = {
  Envelope: ["field_typology", "field_weather"],
  "Envelope.Assemblies": ["field_typology", "field_age_group"],
  "Envelope.Infiltration": ["field_weather"],
  Operations: ["field_region"],
  "Operations.SpaceUse": ["field_typology", "field_age"],
  "Operations.HVAC": ["field_region", "field_age_group"],
  "Operations.HVAC.ConditioningSystems.Heating": ["field_age_group"],
  "Operations.DHW": ["field_region", "field_size_band"]
};

export const buildInitialFields = (): SemanticField[] => [
  ...baseSemanticFields,
  ...derivedSemanticFields
];

export const buildInitialLinks = (): Record<string, string[]> =>
  structuredClone(fieldLinks);

export const createDerivedOptions = (
  derivedType: DerivedFieldType,
  rangeMapping: RangeMapping[],
  groupMapping: Record<string, string[]>
): string[] => {
  if (derivedType === "numeric_range") {
    const labels = rangeMapping.map((range) => range.label);
    return Array.from(new Set([...labels, "other"]));
  }
  const groups = Object.keys(groupMapping);
  return Array.from(new Set(groups));
};
