export type PrismaComponentNode = {
  displayName: string;
  description: string;
  children: string[];
};

export const PRISMA_COMPONENTS: Record<string, PrismaComponentNode> = {
  Envelope: {
    displayName: "Envelope",
    description: "building envelope assembly including constructions and infiltration",
    children: [
      "Assemblies",
      "Infiltration",
      "AtticInfiltration",
      "BasementInfiltration",
      "Window"
    ]
  },
  Operations: {
    displayName: "Operations",
    description: "building operations including space use, hvac, and dhw",
    children: ["SpaceUse", "HVAC", "DHW"]
  },
  Assemblies: {
    displayName: "Envelope Assemblies",
    description: "envelope assembly (envelopeassembly)",
    children: [
      "FlatRoofAssembly",
      "AtticRoofAssembly",
      "AtticFloorAssembly",
      "FacadeAssembly",
      "FloorCeilingAssembly",
      "PartitionAssembly",
      "ExternalFloorAssembly",
      "GroundSlabAssembly",
      "GroundWallAssembly",
      "BasementCeilingAssembly",
      "InternalMassAssembly"
    ]
  },
  SpaceUse: {
    displayName: "Space Use",
    description: "space use combining occupancy, lighting, equipment, thermostat, and water use",
    children: ["Occupancy", "Lighting", "Equipment", "Thermostat", "WaterUse"]
  },
  HVAC: {
    displayName: "HVAC",
    description: "hvac system combining conditioning and ventilation",
    children: ["ConditioningSystems", "Ventilation"]
  },
  ConditioningSystems: {
    displayName: "Conditioning Systems",
    description: "heating and cooling systems",
    children: ["Heating", "Cooling"]
  },
  Infiltration: {
    displayName: "Infiltration",
    description: "main infiltration component",
    children: []
  },
  AtticInfiltration: {
    displayName: "Attic Infiltration",
    description: "attic infiltration component",
    children: []
  },
  BasementInfiltration: {
    displayName: "Basement Infiltration",
    description: "basement infiltration component",
    children: []
  },
  Window: {
    displayName: "Window",
    description: "glazing construction (glazingconstructionsimple)",
    children: []
  },
  Occupancy: {
    displayName: "Occupancy",
    description: "occupancy schedule and density",
    children: []
  },
  Lighting: {
    displayName: "Lighting",
    description: "lighting power density and schedule",
    children: []
  },
  Equipment: {
    displayName: "Equipment",
    description: "equipment power density and schedule",
    children: []
  },
  Thermostat: {
    displayName: "Thermostat",
    description: "heating and cooling setpoints with schedules",
    children: []
  },
  WaterUse: {
    displayName: "Water Use",
    description: "domestic hot water use",
    children: []
  },
  DHW: {
    displayName: "DHW",
    description: "domestic hot water system",
    children: []
  },
  Ventilation: {
    displayName: "Ventilation",
    description: "ventilation system",
    children: []
  },
  Heating: {
    displayName: "Heating",
    description: "heating thermal system",
    children: []
  },
  Cooling: {
    displayName: "Cooling",
    description: "cooling thermal system",
    children: []
  },
  FlatRoofAssembly: {
    displayName: "Flat Roof",
    description: "flat roof construction assembly",
    children: []
  },
  AtticRoofAssembly: {
    displayName: "Attic Roof",
    description: "attic roof construction assembly",
    children: []
  },
  AtticFloorAssembly: {
    displayName: "Attic Floor",
    description: "attic floor construction assembly",
    children: []
  },
  FacadeAssembly: {
    displayName: "Facade",
    description: "facade/wall construction assembly",
    children: []
  },
  FloorCeilingAssembly: {
    displayName: "Floor/Ceiling",
    description: "interior floor/ceiling assembly",
    children: []
  },
  PartitionAssembly: {
    displayName: "Partition",
    description: "interior partition wall assembly",
    children: []
  },
  ExternalFloorAssembly: {
    displayName: "External Floor",
    description: "external floor assembly",
    children: []
  },
  GroundSlabAssembly: {
    displayName: "Ground Slab",
    description: "ground slab construction assembly",
    children: []
  },
  GroundWallAssembly: {
    displayName: "Ground Wall",
    description: "ground wall construction assembly",
    children: []
  },
  BasementCeilingAssembly: {
    displayName: "Basement Ceiling",
    description: "basement ceiling assembly",
    children: []
  },
  InternalMassAssembly: {
    displayName: "Internal Mass",
    description: "internal mass assembly",
    children: []
  }
};
