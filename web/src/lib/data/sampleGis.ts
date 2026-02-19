export type FieldType = "numeric" | "categorical";

export type GisField = {
  name: string;
  type: FieldType;
  values: string[];
  enabled: boolean;
};

export const sampleFields: GisField[] = [
  {
    name: "Typology",
    type: "categorical",
    values: [
      "res",
      "office",
      "retail",
      "office_small",
      "office_medium",
      "office_large",
      "retail_small",
      "retail_medium",
      "retail_large",
      "school_religious_culture",
      "hospital_welfare",
      "factory_data_etc",
      "warehouse",
      "hotel"
    ],
    enabled: true
  },
  {
    name: "Height",
    type: "numeric",
    values: ["5", "10", "15", "20"],
    enabled: true
  },
  {
    name: "YearBuilt",
    type: "numeric",
    values: ["1980", "1995", "2005", "2018"],
    enabled: true
  },
  {
    name: "ConstructionType",
    type: "categorical",
    values: ["steel", "concrete", "wood"],
    enabled: true
  }
];
