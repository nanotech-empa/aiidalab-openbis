from pydantic import (
    BaseModel,
    Field,
    model_validator,
    field_validator,
)
from typing import List, Union, Dict, Optional
from enum import Enum
import re
from datetime import datetime

# Enums


class ComponentMainCategoryEnum(str, Enum):
    Auxiliary = "Auxiliary"
    Microscope_Core_Components = "Microscope Core Components"
    Sample_Preparation_Handling = "Sample Preparation & Handling"
    Vacuum_System = "Vacuum System"


class ComponentSubCategoryEnum(str, Enum):
    Auxiliary = "Auxiliary"
    Analyser = "Analyser"
    Control_Data_Acquisition = "Control and Data Acquisition"
    Gauge = "Gauge"
    Mechanical_Component = "Mechanical Component"
    Preparation_Tools = "Preparation Tools"
    Pump = "Pump"
    STM = "STM"
    Temperature_Environment_Control = "Temperature and Environment Control"
    Vacuum_Chamber = "Vacuum Chamber"


class DraftTypeEnum(str, Enum):
    Preprint = "Preprint"
    Postprint = "Postprint"


class ObjectStatusEnum(str, Enum):
    Active = "Active"
    Broken = "Broken"
    Disposed = "Disposed"
    Inactive = "Inactive"


class AngleUnitEnum(str, Enum):
    Degree = "deg"
    Radian = "rad"


class CurrentUnitEnum(str, Enum):
    Ampere = "A"
    Milliampere = "mA"
    Microampere = "uA"


class DensityUnitEnum(str, Enum):
    Grams_per_Cubic_Centimiter = "g/cm3"


class EnergyUnitEnum(str, Enum):
    Joule = "J"
    ElectronVolt = "eV"
    Hartree = "Ha"


class MassUnitEnum(str, Enum):
    Gram = "g"
    Milligram = "mg"
    Microgram = "ug"


class TemperatureUnitEnum(str, Enum):
    Celsius = "C"
    Kelvin = "K"
    Fahrenheit = "F"


class PressureUnitEnum(str, Enum):
    Millibar = "mBar"
    Bar = "Bar"
    Pascal = "Pa"
    KiloPascal = "kPa"


class VoltageUnitEnum(str, Enum):
    Kilovolt = "kV"
    Volt = "V"
    Millivolt = "mV"
    Microvolt = "uV"


class VolumeUnitEnum(str, Enum):
    Liter = "l"
    Milliliter = "ml"
    Microliter = "ul"


class SpecialStorageConditionsEnum(str, Enum):
    Dry = "Dry"
    No_Oxygen = "No Oxygen"
    Fridge = "Fridge"
    Freezer = "Freezer"
    Dark = "Dark"
    Flammable = "Flammable"
    Poisonous = "Poisonous"


class CurrencyUnitEnum(str, Enum):
    Euro = "EUR"
    SwissFranc = "CHF"
    USDollar = "USD"


class LengthUnitEnum(str, Enum):
    Meter = "m"
    Millimeter = "mm"
    Micrometer = "um"
    Nanometer = "nm"
    Angstorm = "Ang"


class EnergyDensityUnitEnum(str, Enum):
    ElectronVolt_by_CubicBohr = "eV/Bohr^3"


class FrequencyUnitEnum(str, Enum):
    Hertz = "Hz"
    Kilohertz = "kHz"


class ShapeEnum(str, Enum):
    round = "round"
    reactangular = "reactangular"


class WorkStatusEnum(str, Enum):
    Active = "Active"
    Inactive = "Inactive"


class PathFindingMethodEnum(str, Enum):
    NEB = "Nudged Elastic Band"
    STRING = "String Method"


class NanotechSurfacesSubgroupEnum(str, Enum):
    Research_Management = "Research Management"
    Research_Infrastructure = "Research Infrastructure"
    Carbon_Nanomaterials = "Carbon Nanomaterials"
    Materials_to_Devices = "Materials to Devices"
    Two_D_Quantum_Materials = "2D Quantum Materials"
    Quantum_Magnetism = "Quantum Magnetism"
    Atomistic_Simulations = "Atomistic Simulations"
    Chiral_Surfaces = "Chiral Surfaces"


# Complex properties


class AngleValue(BaseModel):
    value: float
    unit: AngleUnitEnum


class CurrentValue(BaseModel):
    value: float
    unit: CurrentUnitEnum


class CurrencyValue(BaseModel):
    value: float
    unit: CurrencyUnitEnum


class DensityValue(BaseModel):
    value: float
    unit: DensityUnitEnum


class EnergyValue(BaseModel):
    value: float
    unit: EnergyUnitEnum


class EnergyDensityValue(BaseModel):
    value: float
    unit: EnergyDensityUnitEnum


class FrequencyValue(BaseModel):
    value: float
    unit: FrequencyUnitEnum


class LengthValue(BaseModel):
    value: float
    unit: LengthUnitEnum


class MassValue(BaseModel):
    value: float
    unit: MassUnitEnum


class PressureValue(BaseModel):
    value: float
    unit: PressureUnitEnum


class TemperatureValue(BaseModel):
    value: float
    unit: TemperatureUnitEnum


class VoltageValue(BaseModel):
    value: float
    unit: VoltageUnitEnum


class VolumeValue(BaseModel):
    value: float
    unit: VolumeUnitEnum


class ComponentActionSettings(BaseModel):
    action_type: str = Field(default="", description="Type of action")
    component_properties: List[str] = Field(
        default_factory=list,
        description="Properties of the component that are used by this action type",
    )


class ObservableReading(BaseModel):
    reading_source: str = Field(default="", description="Reading source name")
    reading_unit: str = Field(default="", description="Reading unit")
    reading_variable: str = Field(
        default="", description="Reading variable"
    )  # TODO: Ask Bruno what is this


class ComponentObservableSettings(BaseModel):
    observable_type: str = Field(default="", description="Type of observable")
    component_properties: List[str] = Field(
        default_factory=list,
        description="List of properties of the component that are used by this observable type",
    )
    observable_readings: List[ObservableReading] = Field(
        default_factory=list, description="List of readings (channels) details"
    )


class CrystalLatticeParameters(BaseModel):
    values: List[float] = Field(
        default_factory=list, description="List of lattice values"
    )
    units: List[Union[LengthValue, AngleValue]] = Field(
        default_factory=list, description="List of lattice values units"
    )


class Dimensions(BaseModel):
    shape: ShapeEnum = Field(default="rectangular", description="Shape of the object")
    diameter: LengthValue = Field(default=None, description="Diameter for round shapes")
    width: LengthValue = Field(default=None, description="Width of the object")
    height: LengthValue = Field(default=None, description="Height of the object")
    thickness: LengthValue = Field(default=None, description="Thickness of the object")

    @model_validator(mode="after")
    def validate_shape_dimensions(self):
        if self.shape == "round" and self.diameter is None:
            raise ValueError("Diameter is required for round shapes")
        return self


class MaterialCoating(BaseModel):
    material: str
    face: str
    thickness: LengthValue


class HeterostructureStack(BaseModel):
    impurities: str
    material: str
    thickness: LengthValue
    source: str


class ActionSettings(BaseModel):
    action_type: str = Field(default="")
    action: Union[
        "Annealing",
        "Coating",
        "Cooldown",
        "Deposition",
        "Delamination",
        "Dosing",
        "Etching",
        "Fishing",
        "FieldEmission",
        "LightIrradiation",
        "MechanicalPressing",
        "Rinse",
        "Sputtering",
    ] = Field(default=None)


class ObservableSettings(BaseModel):
    observable_type: str = Field(default="")
    observable: Union[
        "CurrentObservable",
        "ElementalCompositionObservable",
        "FluxObservable",
        "ForceObservable",
        "InductanceObservable",
        "PHValueObservable",
        "PressureObservable",
        "ResistanceObservable",
        "SpeedObservable",
        "TemperatureObservable",
        "VoltageObservable",
    ] = Field(default=None)


class ProcessStepSettings(BaseModel):
    name: str = Field(default="")
    description: str = Field(default="")
    instrument: str = Field(default="")
    comments: str = Field(default="")
    actions_settings: List[ActionSettings] = Field(default_factory=list)
    observables_settings: List[ObservableSettings] = Field(default_factory=list)


class EvaporationTemperature(BaseModel):
    measurement_datetime: datetime = None
    instrument_name: str = Field(default="")
    temperature: TemperatureValue = None


# Objects
class OpenBISObject(BaseModel):
    permId: str = Field(
        default="",
        title="PermID",
        description="Permanent identifier for the OpenBIS object",
        metadata={"type": "No type"},
    )
    name: str = Field(
        default="",
        title="Name",
        description="Name of the OpenBIS object",
        metadata={"type": "VARCHAR"},
    )
    description: str = Field(
        default="",
        title="Description",
        description="Description of the OpenBIS object",
        metadata={"type": "VARCHAR"},
    )
    default_object_view: str = Field(
        default=None,
        title="Default object view",
        description="Default object view",
        metadata={"type": "No type"},
    )
    registration_date: str = Field(
        default="",
        title="Registration date",
        description="Date when the object was registered",
        metadata={"type": "No type"},
    )
    comments: str = Field(
        default="",
        title="Comments",
        description="Additional comments about the object",
        metadata={"type": "MULTILINE_VARCHAR"},
    )


class Grant(OpenBISObject):
    project_id: str = Field(
        default=None,
        title="Project ID",
        description="Identifier of the project",
        metadata={"type": "VARCHAR"},
    )
    acknowledgement_sentence: str = Field(
        default=None,
        title="Acknowledgement sentence",
        description="Acknowledgement sentence",
        metadata={"type": "MULTILINE_VARCHAR"},
    )
    budget: CurrencyValue = Field(
        default=None,
        title="Budget",
        description="Budget allocated",
        metadata={"type": "JSON"},
    )
    start_date: str = Field(
        default=None,
        title="Start date",
        description="Start date in 'YYYY-MM-DD' format",
        metadata={"type": "DATE"},
    )
    end_date: str = Field(
        default=None,
        title="End date",
        description="End date in 'YYYY-MM-DD' format",
        metadata={"type": "DATE"},
    )
    funder_name: str = Field(
        default=None,
        title="Funder name",
        description="Name of the funder",
        metadata={"type": "VARCHAR"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "GRNT"

    @classmethod
    def get_label(cls) -> str:
        return "Grant"

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be in 'YYYY-MM-DD' format.")
        return v

    @model_validator(mode="after")
    def check_date_order(cls, model):
        if model.start_date and model.end_date:
            start = datetime.strptime(model.start_date, "%Y-%m-%d")
            end = datetime.strptime(model.end_date, "%Y-%m-%d")
            if end < start:
                raise ValueError(
                    "end_date must be greater than or equal to start_date."
                )
        return model


class Organisation(OpenBISObject):
    address: str = Field(
        default="",
        title="Address",
        description="Address of the organisation",
        metadata={"type": "VARCHAR"},
    )
    email: str = Field(
        default="",
        title="Email",
        description="Email address of the organisation",
        metadata={"type": "VARCHAR"},
    )
    work_phone: str = Field(
        default="",
        title="Work phone",
        description="Work phone number of the organisation",
        metadata={"type": "VARCHAR"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "ORGA"

    @classmethod
    def get_label(cls) -> str:
        return "Organisation"


class Group(OpenBISObject):
    group: "Group" = Field(
        default=None,
        title="Group",
        description="Parent group (if applicable)",
        metadata={"type": "SAMPLE"},
    )
    organisation: Organisation = Field(
        default=None,
        title="Organisation",
        description="Organisation to which the group belongs to",
        metadata={"type": "SAMPLE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "GROP"

    @classmethod
    def get_label(cls) -> str:
        return "Group"


class Person(OpenBISObject):
    username: str = Field(
        default="",
        title="Username",
        description="Username of the person",
        metadata={"type": "VARCHAR"},
    )
    email: str = Field(
        default="",
        title="Email",
        description="Email address of the person",
        metadata={"type": "VARCHAR"},
    )
    mobile_phone: str = Field(
        default="",
        title="Mobile phone",
        description="Mobile phone number",
        metadata={"type": "VARCHAR"},
    )
    work_phone: str = Field(
        default="",
        title="Work phone",
        description="Work phone number",
        metadata={"type": "VARCHAR"},
    )
    work_status: WorkStatusEnum = Field(
        default="Active",
        title="Work status",
        description="Current work status",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    office: "Room" = Field(
        default=None,
        title="Office",
        description="Working office",
        metadata={"type": "SAMPLE"},
    )
    organisations: List[Organisation] = Field(
        default_factory=list,
        title="Organisation(s)",
        description="Organisation(s) to which the person belongs. Only used if the person does not belong to any group.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    groups: List[Group] = Field(
        default_factory=list,
        title="Group(s)",
        description="Group(s) to which the person belongs",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    nanotech_surfaces_subgroup: NanotechSurfacesSubgroupEnum = Field(
        default=None,
        title="nanotech@surfaces subgroup",
        description="Subgroup of nanotech@surfaces at Empa. Only used for sorting people inside a collection. Not used in people that do not belong to nanotech@surfaces.",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "PERS"

    @classmethod
    def get_label(cls) -> str:
        return "Person"


class Author(OpenBISObject):
    person: Person = Field(
        default=None,
        title="Person",
        description="Person",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    groups: List[Group] = Field(
        default=None,
        title="Group(s)",
        description="Group(s) to which the person belonged when the publication was done",
        metadata={"type": "SAMPLE", "multivalue": True},
    )

    @classmethod
    def get_code(cls) -> str:
        return "AUTH"

    @classmethod
    def get_label(cls) -> str:
        return "Author"


class Molecule(OpenBISObject):
    empa_number: int = Field(
        default=0,
        title="Empa number",
        ge=1,
        description="Integer value given to new substances inside Empa (0 = unassigned)",
        metadata={"type": "INTEGER"},
    )
    smiles: str = Field(
        default="",
        title="SMILES",
        description="SMILES string for the substance, e.g. CCO",
        metadata={"type": "VARCHAR"},
    )
    sum_formula: str = Field(
        default="",
        title="Sum formula",
        description="Molecular sum formula, e.g. CH4",
        metadata={"type": "VARCHAR"},
    )
    cas_number: str = Field(
        default="",
        title="CAS number",
        description="Unique numerical identifier assigned to a specific chemical substance by the Chemical Abstracts Service (CAS), e.g. 58-08-2",
        metadata={"type": "VARCHAR"},
    )
    iupac_name: str = Field(
        default="",
        title="IUPAC name",
        description="IUPAC standardised chemical name, e.g. 1,3,7-Trimethyl-3,7-dihydro-1H-purine-2,6-dione for caffeine.",
        metadata={"type": "VARCHAR"},
    )
    substances: List["Substance"] = Field(
        default_factory=list,
        title="Substance(s)",
        description="List of substances that contain this molecule",
        metadata={"type": "SAMPLE", "multivalue": True},
    )

    @classmethod
    def get_code(cls) -> str:
        return "MOLE"

    @classmethod
    def get_label(cls) -> str:
        return "Molecule"


class GasBottle(OpenBISObject):
    molecules: List[Molecule] = Field(
        default_factory=list,
        title="Molecules",
        description="List of molecules that gas bottle contains",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    amount: Optional[Union[MassValue, VolumeValue]] = Field(
        default=None,
        title="Amount",
        description="Amount of gas",
        metadata={"type": "JSON"},
    )
    location: Optional[Union["Instrument", "InstrumentSTM", "Room"]] = Field(
        default=None,
        title="Location",
        description="Storage location",
        metadata={"type": "SAMPLE"},
    )
    special_storage_conditions: List[SpecialStorageConditionsEnum] = Field(
        default_factory=list,
        title="Special storage condition(s)",
        description="Special storage conditions required",
        metadata={"type": "CONTROLLEDVOCABULARY", "multivalue": True},
    )
    package_opening_date: str = Field(
        default="",
        title="Package opening date",
        description="Date when package was opened",
        metadata={"type": "DATE"},
    )
    object_status: ObjectStatusEnum = Field(
        default=ObjectStatusEnum.Active,
        title="Object status",
        description="Current status of the object",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    supplier: Organisation = Field(
        default=None,
        title="Supplier",
        description="Supplier information",
        metadata={"type": "SAMPLE"},
    )
    receive_date: str = Field(
        default=None,
        title="Receive date",
        description="Date when the gas bottle was received",
        metadata={"type": "DATE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "GASB"

    @classmethod
    def get_label(cls) -> str:
        return "Gas Bottle"

    @field_validator("receive_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class Substance(OpenBISObject):
    molecules: List[Molecule] = Field(
        default_factory=list,
        title="Molecule(s)",
        description="List of molecules that substance contains",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    empa_number: int = Field(
        default=0,
        title="Empa number",
        ge=1,
        description="Integer value given to new substances inside Empa (0 = unassigned)",
        metadata={"type": "INTEGER"},
    )
    batch: str = Field(
        default="",
        title="Batch",
        description="Letter given to the batch of substances, e.g., a for the first, b for the second.",
        metadata={"type": "VARCHAR"},
    )
    vial: str = Field(
        default="",
        title="Vial",
        description="Letter given to the vial of the batch of substances, e.g. i, ii, iii.",
        metadata={"type": "VARCHAR"},
    )
    evaporation_temperatures: EvaporationTemperature = Field(
        default_factory=list,
        title="Evaporation temperature(s)",
        description="Evaporation temperatures",
        metadata={"type": "XML", "custom_widget": "Spreadsheet"},
    )
    purity: float = Field(
        default=0.0,
        title="Purity",
        description="Purity of the substance",
        metadata={"type": "REAL"},
    )
    substance_type: str = Field(
        default="",
        title="Substance type",
        description="Type of the substance, e.g. Solvent",
        metadata={"type": "VARCHAR"},
    )
    amount: Optional[Union[MassValue, VolumeValue]] = Field(
        default=None,
        title="Amount",
        description="Amount of substance",
        metadata={"type": "JSON"},
    )
    location: Optional[Union["Instrument", "InstrumentSTM", "Room"]] = Field(
        default=None,
        title="Location",
        description="Storage location",
        metadata={"type": "SAMPLE"},
    )
    special_storage_conditions: List[SpecialStorageConditionsEnum] = Field(
        default_factory=list,
        title="Special storage condition(s)",
        description="Special storage conditions required",
        metadata={"type": "CONTROLLEDVOCABULARY", "multivalue": True},
    )
    package_opening_date: str = Field(
        default="",
        title="Package opening date",
        description="Date when package was opened",
        metadata={"type": "DATE"},
    )
    object_status: ObjectStatusEnum = Field(
        default=ObjectStatusEnum.Active,
        title="Object status",
        description="Current status of the object",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    supplier: Organisation = Field(
        default=None,
        title="Supplier",
        description="Supplier information",
        metadata={"type": "SAMPLE"},
    )
    synthesised_by: List[Person] = Field(
        default_factory=list,
        title="Synthesised by",
        description="List of people who synthesized the substance",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    supplier_own_name: str = Field(
        default="",
        title="Supplier own name",
        description="Supplier's own name for the substance",
        metadata={"type": "VARCHAR"},
    )
    receive_date: str = Field(
        default=None,
        title="Receive date",
        description="Date when the substance was received",
        metadata={"type": "DATE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "SUBS"

    @classmethod
    def get_label(cls) -> str:
        return "Substance"

    @field_validator("receive_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class CrystalConcept(OpenBISObject):
    face: str = Field(
        default="",
        title="Face",
        description="Crystal face information",
        metadata={"type": "VARCHAR"},
    )
    material: str = Field(
        default="",
        title="Material",
        description="Material of the crystal",
        metadata={"type": "VARCHAR"},
    )
    lattice_parameters: CrystalLatticeParameters = Field(
        default=None,
        title="Lattice parameters",
        description="Crystal lattice parameters",
        metadata={"type": "JSON"},
    )
    space_group: int = Field(
        default=0,
        title="Crystal space group",
        description="Space group number",
        metadata={"type": "INTEGER"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "CRCO"

    @classmethod
    def get_label(cls) -> str:
        return "Crystal Concept"


class Crystal(OpenBISObject):
    crystal_concept: CrystalConcept = Field(
        default=None,
        title="Crystal concept",
        description="Crystal concept information",
        metadata={"type": "SAMPLE"},
    )
    face: str = Field(
        default="",
        title="Face",
        description="Crystal face information",
        metadata={"type": "VARCHAR"},
    )
    material: str = Field(
        default="",
        title="Material",
        description="Material of the crystal",
        metadata={"type": "VARCHAR"},
    )
    sample_plate: str = Field(
        default=None,
        title="Sample plate",
        description="Identifier for the sample plate",
        metadata={"type": "VARCHAR"},
    )
    dimensions: Dimensions = Field(
        default=None,
        title="Dimensions",
        description="Crystal dimensions",
        metadata={"type": "JSON"},
    )
    reference_number: str = Field(
        default="",
        title="Reference number",
        description="Reference number for the crystal",
        metadata={"type": "VARCHAR"},
    )
    location: Optional[Union["Room", "Instrument", "InstrumentSTM"]] = Field(
        default=None,
        title="Location",
        description="Storage location",
        metadata={"type": "SAMPLE"},
    )
    special_storage_conditions: List[SpecialStorageConditionsEnum] = Field(
        default_factory=list,
        title="Special storage condition(s)",
        description="Special storage conditions required",
        metadata={"type": "CONTROLLEDVOCABULARY", "multivalue": True},
    )
    package_opening_date: str = Field(
        default="",
        title="Package opening date",
        description="Date when package was opened",
        metadata={"type": "DATE"},
    )
    object_status: ObjectStatusEnum = Field(
        default=ObjectStatusEnum.Active,
        title="Object status",
        description="Current status of the object",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    supplier: Organisation = Field(
        default=None,
        title="Supplier",
        description="Supplier information",
        metadata={"type": "SAMPLE"},
    )
    synthesised_by: List[Person] = Field(
        default_factory=list,
        title="Synthesised by",
        description="List of people who synthesized the crystal",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    supplier_own_name: str = Field(
        default="",
        title="Supplier own name",
        description="Supplier's own name for the crystal",
        metadata={"type": "VARCHAR"},
    )
    receive_date: str = Field(
        default="",
        title="Receive date",
        description="Date when crystal was received",
        metadata={"type": "DATE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "CRRE"

    @classmethod
    def get_label(cls) -> str:
        return "Crystal"

    @field_validator("receive_date", "package_opening_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class TwoDLayerMaterial(OpenBISObject):
    top_layer_material: str = Field(
        default="",
        title="Top layer material",
        description="Material of the top layer",
        metadata={"type": "VARCHAR"},
    )
    layer_count: str = Field(
        default="",
        title="Number of layers",
        description="Number of layers as string",
        metadata={"type": "VARCHAR"},
    )
    impurities: str = Field(
        default="",
        title="Impurities",
        description="Information about impurities present",
        metadata={"type": "VARCHAR"},
    )
    heterostructure_stack: List[HeterostructureStack] = Field(
        default_factory=list,
        title="Heterostructure stack",
        description="Heterostructure stack",
        metadata={"type": "XML", "custom_widget": "Spreadsheet"},
    )
    substrate: str = Field(
        default="",
        title="Substrate",
        description="Substrate material",
        metadata={"type": "VARCHAR"},
    )
    growth_method: str = Field(
        default="",
        title="Growth/Fabrication method",
        description="Method used for growth",
        metadata={"type": "VARCHAR"},
    )
    dimensions: Dimensions = Field(
        default_factory=Dimensions,
        title="Dimensions",
        description="Dimensions of the 2d layer material",
        metadata={"type": "JSON"},
    )
    location: Optional[Union["Instrument", "InstrumentSTM", "Room"]] = Field(
        default=None,
        title="Location",
        description="Storage location",
        metadata={"type": "SAMPLE"},
    )
    special_storage_conditions: List[SpecialStorageConditionsEnum] = Field(
        default_factory=list,
        title="Special storage condition(s)",
        description="Special storage conditions",
        metadata={"type": "CONTROLLEDVOCABULARY", "multivalue": True},
    )
    package_opening_date: str = Field(
        default=None,
        title="Package opening date",
        description="Date when the package was opened",
        metadata={"type": "DATE"},
    )
    sample_plate: str = Field(
        default=None,
        title="Sample plate",
        description="Sample plate identifier",
        metadata={"type": "VARCHAR"},
    )
    object_status: ObjectStatusEnum = Field(
        default=None,
        title="Object status",
        description="Status of the 2d layer material",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    supplier: Organisation = Field(
        default=None,
        title="Supplier",
        description="Supplier information",
        metadata={"type": "SAMPLE"},
    )
    synthesised_by: List[Person] = Field(
        default_factory=list,
        title="Synthesised by",
        description="List of people who synthesized the 2d layer material",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    supplier_own_name: str = Field(
        default=None,
        title="Supplier own name",
        description="Supplier's own name for the 2d layer material",
        metadata={"type": "VARCHAR"},
    )
    receive_date: str = Field(
        default="",
        title="Receive date",
        description="Date when 2d layer material was received",
        metadata={"type": "DATE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "TDLM"

    @classmethod
    def get_label(cls) -> str:
        return "2D Layer Material"

    @field_validator("receive_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class Stamp(OpenBISObject):
    material: str = Field(
        default=None,
        title="Material",
        description="Material of the stamp",
        metadata={"type": "VARCHAR"},
    )
    location: Optional[Union["Instrument", "InstrumentSTM", "Room"]] = Field(
        default=None,
        title="Location",
        description="Storage location",
        metadata={"type": "SAMPLE"},
    )
    sample_plate: str = Field(
        default=None,
        title="Sample plate",
        description="Sample plate identifier",
        metadata={"type": "VARCHAR"},
    )
    object_status: ObjectStatusEnum = Field(
        default=None,
        title="Object status",
        description="Status of the stamp",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    assembled_by: List[Person] = Field(
        default_factory=list,
        title="Synthesised by",
        description="List of people who assembled the stamp",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    assembled_date: str = Field(
        default="",
        title="Assembled date",
        description="Date when stamp was assembled",
        metadata={"type": "DATE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "STMP"

    @classmethod
    def get_label(cls) -> str:
        return "Stamp"

    @field_validator("assembled_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class Wafer(OpenBISObject):
    material: str = Field(
        default=None,
        title="Material",
        description="Material of the wafer substrate",
        metadata={"type": "VARCHAR"},
    )
    face: str = Field(
        default=None,
        title="Face",
        description="Face orientation of the wafer substrate",
        metadata={"type": "VARCHAR"},
    )
    doping: str = Field(
        default=None,
        title="Doping",
        description="Doping type or level",
        metadata={"type": "VARCHAR"},
    )
    material_coating: List[MaterialCoating] = Field(
        default_factory=list,
        title="Material coating",
        description="Material coating details",
        metadata={"type": "JSON"},
    )
    dimensions: Dimensions = Field(
        default_factory=Dimensions,
        title="Dimensions",
        description="Dimensions of the wafer substrate",
        metadata={"type": "JSON"},
    )
    location: Optional[Union["Instrument", "InstrumentSTM", "Room"]] = Field(
        default=None,
        title="Location",
        description="Storage location",
        metadata={"type": "SAMPLE"},
    )
    special_storage_conditions: List[SpecialStorageConditionsEnum] = Field(
        default_factory=list,
        title="Special storage condition(s)",
        description="Special storage conditions",
        metadata={"type": "CONTROLLEDVOCABULARY", "multivalue": True},
    )
    package_opening_date: str = Field(
        default=None,
        title="Package opening date",
        description="Date when the package was opened",
        metadata={"type": "DATE"},
    )
    sample_plate: str = Field(
        default=None,
        title="Sample plate",
        description="Sample plate identifier",
        metadata={"type": "VARCHAR"},
    )
    object_status: ObjectStatusEnum = Field(
        default=None,
        title="Object status",
        description="Status of the wafer substrate",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    supplier: Organisation = Field(
        default=None,
        title="Supplier",
        description="Supplier information",
        metadata={"type": "SAMPLE"},
    )
    synthesised_by: List[Person] = Field(
        default_factory=list,
        title="Synthesised by",
        description="List of people who synthesized the wafer substrate",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    supplier_own_name: str = Field(
        default=None,
        title="Supplier own name",
        description="Supplier's own name for the wafer substrate",
        metadata={"type": "VARCHAR"},
    )
    receive_date: str = Field(
        default="",
        title="Receive date",
        description="Date when wafer substrate was received",
        metadata={"type": "DATE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "WAFR"

    @classmethod
    def get_label(cls) -> str:
        return "Wafer"

    @field_validator("receive_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class WaferSubstrate(OpenBISObject):
    material: str = Field(
        default=None,
        title="Material",
        description="Material of the wafer",
        metadata={"type": "VARCHAR"},
    )
    face: str = Field(
        default=None,
        title="Face",
        description="Face orientation of the wafer",
        metadata={"type": "VARCHAR"},
    )
    material_coating: List[MaterialCoating] = Field(
        default_factory=list,
        title="Material coating",
        description="Material coating details",
        metadata={"type": "JSON"},
    )
    dimensions: Dimensions = Field(
        default_factory=Dimensions,
        title="Dimensions",
        description="Dimensions of the wafer",
        metadata={"type": "JSON"},
    )
    location: Optional[Union["Instrument", "InstrumentSTM", "Room"]] = Field(
        default=None,
        title="Location",
        description="Storage location",
        metadata={"type": "SAMPLE"},
    )
    special_storage_conditions: List[SpecialStorageConditionsEnum] = Field(
        default_factory=list,
        title="Special storage condition(s)",
        description="Special storage conditions",
        metadata={"type": "CONTROLLEDVOCABULARY", "multivalue": True},
    )
    package_opening_date: str = Field(
        default=None,
        title="Package opening date",
        description="Date when the package was opened",
        metadata={"type": "DATE"},
    )
    sample_plate: str = Field(
        default=None,
        title="Sample plate",
        description="Sample plate identifier",
        metadata={"type": "VARCHAR"},
    )
    object_status: ObjectStatusEnum = Field(
        default=None,
        title="Object status",
        description="Status of the wafer",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    supplier: Organisation = Field(
        default=None,
        title="Supplier",
        description="Supplier information",
        metadata={"type": "SAMPLE"},
    )
    synthesised_by: List[Person] = Field(
        default_factory=list,
        title="Synthesised by",
        description="List of people who synthesized the wafer",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    supplier_own_name: str = Field(
        default=None,
        title="Supplier own name",
        description="Supplier's own name for the wafer",
        metadata={"type": "VARCHAR"},
    )
    receive_date: str = Field(
        default="",
        title="Receive date",
        description="Date when wafer substrate was received",
        metadata={"type": "DATE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "WFSB"

    @classmethod
    def get_label(cls) -> str:
        return "Wafer Substrate"

    @field_validator("receive_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class Wire(OpenBISObject):
    material: str = Field(
        default=None,
        title="Material",
        description="Material of the wire",
        metadata={"type": "VARCHAR"},
    )
    purity: float = Field(
        default=0.0,
        title="Purity",
        description="Purity level of the wire",
        metadata={"type": "REAL"},
    )
    dimensions: Dimensions = Field(
        default=None,
        title="Dimensions",
        description="Dimensions of the wafer",
        metadata={"type": "JSON"},
    )
    location: Optional[Union["Instrument", "InstrumentSTM", "Room"]] = Field(
        default=None,
        title="Location",
        description="Storage location",
        metadata={"type": "SAMPLE"},
    )
    special_storage_conditions: List[SpecialStorageConditionsEnum] = Field(
        default_factory=list,
        title="Special storage condition(s)",
        description="Special storage conditions",
        metadata={"type": "CONTROLLEDVOCABULARY", "multivalue": True},
    )
    package_opening_date: str = Field(
        default=None,
        title="Package opening date",
        description="Date when the package was opened",
        metadata={"type": "DATE"},
    )
    object_status: ObjectStatusEnum = Field(
        default=None,
        title="Object status",
        description="Status of the wafer",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    supplier: Organisation = Field(
        default=None,
        title="Supplier",
        description="Supplier information",
        metadata={"type": "SAMPLE"},
    )
    synthesised_by: List[Person] = Field(
        default_factory=list,
        title="Synthesised by",
        description="List of people who synthesized the wafer",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    supplier_own_name: str = Field(
        default=None,
        title="Supplier own name",
        description="Supplier's own name for the wafer",
        metadata={"type": "VARCHAR"},
    )
    receive_date: str = Field(
        default="",
        title="Receive date",
        description="Date when wire was received",
        metadata={"type": "DATE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "WIRE"

    @classmethod
    def get_label(cls) -> str:
        return "Wire"

    @field_validator("receive_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class Sample(OpenBISObject):
    object_status: ObjectStatusEnum = Field(
        default=None,
        title="Object status",
        description="Status of the wafer",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    crystal: Crystal = Field(
        default=None,
        title="Crystal",
        description="Crystal structure of the sample",
        metadata={"type": "PARENT"},
    )
    two_d_layer_material: TwoDLayerMaterial = Field(
        default=None,
        title="2D layer material",
        description="2D layer material associated with the sample",
        metadata={"type": "PARENT"},
    )
    wafer_substrate: WaferSubstrate = Field(
        default=None,
        title="Wafer substrate",
        description="Wafer substrate used for the sample",
        metadata={"type": "PARENT"},
    )
    process_step: "ProcessStep" = Field(
        default=None,
        title="Process step",
        description="Process step used to prepare the sample",
        metadata={"type": "PARENT"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "SAMP"

    @classmethod
    def get_label(cls) -> str:
        return "Sample"


class ReactionProductConcept(OpenBISObject):
    sum_formula: str = Field(
        default=None,
        title="Sum formula",
        description="Sum formula of the reaction product concept",
        metadata={"type": "VARCHAR"},
    )
    molecules: List[Molecule] = Field(
        default_factory=list,
        title="Molecule(s)",
        description="List of molecules involved",
        metadata={"type": "SAMPLE", "multivalue": True},
    )

    @classmethod
    def get_code(cls) -> str:
        return "RPCO"

    @classmethod
    def get_label(cls) -> str:
        return "Reaction Product Concept"


class ReactionProduct(OpenBISObject):
    reaction_temperature: TemperatureValue = Field(
        default=None,
        title="Reaction temperature",
        description="Temperature at which the product was obtained",
        metadata={"type": "JSON"},
    )
    reaction_yield: float = Field(
        default=None,
        title="Reaction yield",
        description="Yield of the reaction product",
        metadata={"type": "REAL"},
    )
    reaction_product_concept: ReactionProductConcept = Field(
        default=None,
        title="Reaction product concept",
        description="Concept associated with the reaction product",
        metadata={"type": "SAMPLE"},
    )
    sample: Sample = Field(
        default=None,
        title="Sample",
        description="Sample associated with the reaction product",
        metadata={"type": "PARENT"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "RPRE"

    @classmethod
    def get_label(cls) -> str:
        return "Reaction Product"


class DeviceSubstrate(OpenBISObject):
    location: Optional[Union["Room", "Instrument", "InstrumentSTM"]] = Field(
        default=None,
        title="Location",
        description="Location of the substrate",
        metadata={"type": "SAMPLE"},
    )
    special_storage_conditions: List[SpecialStorageConditionsEnum] = Field(
        default_factory=list,
        title="Special storage condition(s)",
        description="List of special storage requirements",
        metadata={"type": "CONTROLLEDVOCABULARY", "multivalue": True},
    )
    sample_plate: str = Field(
        default=None,
        title="Sample plate",
        description="Identifier for the sample plate",
        metadata={"type": "VARCHAR"},
    )
    object_status: ObjectStatusEnum = Field(
        default="Active",
        title="Object status",
        description="Current status of the object",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    supplier: Organisation = Field(
        default=None,
        title="Supplier",
        description="Supplier information",
        metadata={"type": "SAMPLE"},
    )
    synthesied_by: List[Person] = Field(
        default_factory=list,
        title="Synthesised by",
        description="List of people who synthesized the device substrate",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    supplier_own_name: str = Field(
        default=None,
        title="Supplier own name",
        description="Supplier-specific name for the substrate",
        metadata={"type": "VARCHAR"},
    )
    receive_date: str = Field(
        default=None,
        title="Receive date",
        description="Date when the device substrate was received",
        metadata={"type": "DATE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "DVSB"

    @classmethod
    def get_label(cls) -> str:
        return "Device Substrate"

    @field_validator("receive_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class WaferSample(OpenBISObject):
    @classmethod
    def get_code(cls) -> str:
        return "WFSB"

    @classmethod
    def get_label(cls) -> str:
        return "Wafer Substrate"


class SampleHolder(OpenBISObject):
    location: Optional[Union["Room", "Instrument", "InstrumentSTM"]] = Field(
        default=None,
        title="Location",
        description="Location of the sample holder",
        metadata={"type": "SAMPLE"},
    )
    receive_date: str = Field(
        default=None,
        title="Receive date",
        description="Date when the sample holder was received",
        metadata={"type": "DATE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "SPHD"

    @classmethod
    def get_label(cls) -> str:
        return "Sample Holder"


class Component(OpenBISObject):
    main_category: ComponentMainCategoryEnum = Field(
        default="",
        title="Main category",
        description="Main category of the component",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    sub_category: ComponentSubCategoryEnum = Field(
        default="",
        title="Sub category",
        description="Sub category of the component",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    manufacturer: Optional[Union[Organisation, Person]] = Field(
        default=None,
        title="Manufacturer",
        description="Manufacturer of the component",
        metadata={"type": "SAMPLE"},
    )
    model: str = Field(
        default="",
        title="Model",
        description="Model of the component",
        metadata={"type": "VARCHAR"},
    )
    serial_number: str = Field(
        default="",
        title="Serial number",
        description="Serial number of the component",
        metadata={"type": "VARCHAR"},
    )
    empa_id: str = Field(
        default="",
        title="Empa ID",
        description="ID given to expensive tools at Empa.",
        metadata={"type": "VARCHAR"},
    )
    location: Optional[Union["Room", "Instrument", "InstrumentSTM"]] = Field(
        default=None,
        title="Location",
        description="Current location of the component",
        metadata={"type": "SAMPLE"},
    )
    object_status: ObjectStatusEnum = Field(
        default=ObjectStatusEnum.Active,
        title="Object status",
        description="Current status of the component",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    actions_settings: List[ComponentActionSettings] = Field(
        default_factory=list,
        title="Actions settings",
        description="Action types that use this component together with the names of the component properties that the action types use.",
        metadata={"type": "JSON"},
    )
    observables_settings: List[ComponentObservableSettings] = Field(
        default_factory=list,
        title="Observables settings",
        description="Observable types that use this component together with the names of the component properties that the observable types use and the readings that the observable type comprise.",
        metadata={"type": "JSON"},
    )
    receive_date: str = Field(
        default="",
        title="Receive date",
        description="Date when component was received",
        metadata={"type": "DATE"},
    )
    ilog: bool = Field(
        default=False,
        title="iLog",
        description="This is the iLog identifier",
        metadata={"type": "BOOLEAN"},
    )
    valid_from: str = Field(
        default="",
        title="Valid From",
        description="Valid From",
        metadata={"type": "VARCHAR"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "COMP"

    @classmethod
    def get_label(cls) -> str:
        return "Component"

    @field_validator("receive_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class Analyser(Component):
    density: DensityValue = Field(
        default=None,
        title="Density",
        description="Density value",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "ANLS"

    @classmethod
    def get_label(cls) -> str:
        return "Analyser"


class Chamber(Component):
    @classmethod
    def get_code(cls) -> str:
        return "CHBR"

    @classmethod
    def get_label(cls) -> str:
        return "Chamber"


class Cryostat(Component):
    target_temperature: TemperatureValue = Field(
        default=None,
        title="Target temperature",
        description="Target temperature",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "CRYO"

    @classmethod
    def get_label(cls) -> str:
        return "Cryostat"


class Electronics(Component):
    @classmethod
    def get_code(cls) -> str:
        return "ELTR"

    @classmethod
    def get_label(cls) -> str:
        return "Electronics"


class EvaporatorSlot(Component):
    target_temperature: TemperatureValue = Field(
        default=None,
        title="Target temperature",
        description="Target temperature for evaporation of the substance in it.",
        metadata={"type": "JSON"},
    )
    slot_number: int = Field(
        default=1,
        title="Slot number",
        strict=True,
        ge=1,
        le=6,
        description="Number of the evaporator slot.",
        metadata={"type": "INTEGER"},
    )
    p_value: float = Field(
        default=0,
        title="P value",
        strict=True,
        ge=0,
        description="P-value",
        metadata={"type": "REAL"},
    )
    i_value: float = Field(
        default=0,
        title="I value",
        strict=True,
        ge=0,
        description="I-value",
        metadata={"type": "REAL"},
    )
    ep_percentage: float = Field(
        default=0,
        title="EP (%)",
        strict=True,
        ge=0,
        le=100,
        description="EP percentage",
        metadata={"type": "REAL"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "EVPS"

    @classmethod
    def get_label(cls) -> str:
        return "Evaporator Slot"


class Evaporator(Component):
    evaporator_slots: List[EvaporatorSlot] = Field(
        default_factory=list,
        title="Evaporator slot(s)",
        description="List of evaporator slots attached to the evaporator.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    target_temperature: TemperatureValue = Field(
        default=None,
        title="Target temperature",
        description="Target temperature for evaporation of the substance in it.",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "EVAP"

    @classmethod
    def get_label(cls) -> str:
        return "Evaporator"


class IonGauge(Component):
    filament: str = Field(
        default="",
        title="Filament",
        description="Filament material",
        metadata={"type": "VARCHAR"},
    )
    filament_current: CurrentValue = Field(
        default=None,
        title="Filament current",
        description="Filament current",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "IONG"

    @classmethod
    def get_label(cls) -> str:
        return "Ion Gauge"


class IonPump(Component):
    @classmethod
    def get_code(cls) -> str:
        return "IONP"

    @classmethod
    def get_label(cls) -> str:
        return "Ion Pump"


class PBNStage(Component):
    target_temperature: TemperatureValue = Field(
        default=None,
        title="Target temperature",
        description="Target temperature for evaporation of the substance in it.",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "PBNS"

    @classmethod
    def get_label(cls) -> str:
        return "PBN Stage"


class SputterGun(Component):
    bias_voltage: VoltageValue = Field(
        default=None,
        title="Bias voltage",
        description="Bias voltage set in the sputter gun.",
        metadata={"type": "JSON"},
    )
    discharge_voltage: VoltageValue = Field(
        default=None,
        title="Discharge voltage",
        description="Discharge voltage set in the sputter gun.",
        metadata={"type": "JSON"},
    )
    discharge_current: CurrentValue = Field(
        default=None,
        title="Discharge current",
        description="Discharge current set in the sputter gun.",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "SPTG"

    @classmethod
    def get_label(cls) -> str:
        return "Sputter Gun"


class ScrollPump(Component):
    @classmethod
    def get_code(cls) -> str:
        return "SCLP"

    @classmethod
    def get_label(cls) -> str:
        return "Scroll Pump"


class AFMSensor(Component):
    wire: Wire = Field(
        default="",
        title="Wire",
        description="Wire used in the AFM sensor",
        metadata={"type": "SAMPLE"},
    )
    fabrication_date: str = Field(
        default=None,
        title="Fabrication date",
        description="Date when the STM tip was received",
        metadata={"type": "DATE"},
    )
    fabrication_method: str = Field(
        default="",
        title="Fabrication method",
        description="Method used to produce the AFM sensor",
        metadata={"type": "VARCHAR"},
    )
    resonance_frequency: FrequencyValue = Field(
        default=None,
        title="Resonance frequency",
        description="Resonance frequency of the AFM sensor.",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "AFMS"

    @classmethod
    def get_label(cls) -> str:
        return "AFM Sensor"

    @field_validator("fabrication_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class STMTip(Component):
    wire: Wire = Field(
        default="",
        title="Wire",
        description="Wire used in the STM sensor",
        metadata={"type": "SAMPLE"},
    )
    fabrication_date: str = Field(
        default=None,
        title="Fabrication date",
        description="Date when the STM tip was received",
        metadata={"type": "DATE"},
    )
    fabrication_method: str = Field(
        default="",
        title="Fabrication method",
        description="Method used to produce the STM tip",
        metadata={"type": "VARCHAR"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "STMT"

    @classmethod
    def get_label(cls) -> str:
        return "STM Tip"

    @field_validator("fabrication_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class Thyracont(Component):
    @classmethod
    def get_code(cls) -> str:
        return "THYR"

    @classmethod
    def get_label(cls) -> str:
        return "Thyracont"


class TurboPump(Component):
    @classmethod
    def get_code(cls) -> str:
        return "TRBP"

    @classmethod
    def get_label(cls) -> str:
        return "Turbo Pump"


class Valve(Component):
    @classmethod
    def get_code(cls) -> str:
        return "VALV"

    @classmethod
    def get_label(cls) -> str:
        return "Valve"


class Instrument(OpenBISObject):
    manufacturer: Organisation = Field(
        default=None,
        title="Manufacturer",
        description="Manufacturer of the instrument",
        metadata={"type": "SAMPLE"},
    )
    model: str = Field(
        default=None,
        title="Model",
        description="Model number",
        metadata={"type": "VARCHAR"},
    )
    serial_number: str = Field(
        default=None,
        title="Serial number",
        description="Serial number",
        metadata={"type": "VARCHAR"},
    )
    empa_id: str = Field(
        default="",
        title="Empa ID",
        description="ID given to expensive tools at Empa.",
        metadata={"type": "VARCHAR"},
    )
    location: "Room" = Field(
        default=None,
        title="Location",
        description="Physical location",
        metadata={"type": "SAMPLE"},
    )
    object_status: ObjectStatusEnum = Field(
        default=None,
        title="Object status",
        description="Status of the instrument",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    responsibles: List[Person] = Field(
        default_factory=list,
        title="Responsible(s)",
        description="List of responsible persons",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    receive_date: str = Field(
        default=None,
        title="Receive date",
        description="Date when the instrument was received",
        metadata={"type": "DATE"},
    )
    ilog: bool = Field(
        default=False,
        title="iLog",
        description="This is the iLog identifier",
        metadata={"type": "BOOLEAN"},
    )
    valid_from: str = Field(
        default="",
        title="ValidFrom",
        description="ValidFrom",
        metadata={"type": "VARCHAR"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "ISTR"

    @classmethod
    def get_label(cls) -> str:
        return "Instrument"

    @field_validator("receive_date")
    @classmethod
    def validate_receive_date(cls, v: str) -> str:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("receive_date must be in 'YYYY-MM-DD' format.")
        return v


class InstrumentSTM(Instrument):
    # Vacuum system
    pumps: List[Union[IonPump, ScrollPump, TurboPump]] = Field(
        default_factory=list,
        title="Pump(s)",
        description="Pumps attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    gauges: List[Union[IonGauge]] = Field(
        default_factory=list,
        title="Gauge(s)",
        description="Gauges attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    vacuum_chambers: List[Chamber] = Field(
        default_factory=list,
        title="Vacuum chamber(s)",
        description="Vacuum chambers attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    ports_valves: List[Union[Component, Valve]] = Field(
        default_factory=list,
        title="Port(s)/valve(s)",
        description="Ports and valves attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    # Sample Preparation & Handling
    preparation_tools: List[
        Union[Component, PBNStage, SputterGun, Valve, Evaporator, Cryostat]
    ] = Field(
        default_factory=list,
        title="Preparation tool(s)",
        description="Preparation tools attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    analysers: List[Analyser] = Field(
        default_factory=list,
        title="Analyser(s)",
        description="Analysers attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    mechanical_components: List[Component] = Field(
        default_factory=list,
        title="Mechanical component(s)",
        description="Mechanical components attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    # Microscope Core Components
    stm_components: List[Union[Component, Electronics, STMTip, AFMSensor]] = Field(
        default_factory=list,
        title="STM component(s)",
        description="STM components attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    control_data_acquisition: List[Electronics] = Field(
        default_factory=list,
        title="Control and data acquisition component(s)",
        description="Control and data acquisition components attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    temperature_environment_control: List[Union[Component, Cryostat]] = Field(
        default_factory=list,
        title="Temperature and environment control component(s)",
        description="Temperature and environment control components attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    # Auxiliary
    auxiliary_components: List[Component] = Field(
        default_factory=list,
        title="Auxiliary component(s)",
        description="Auxiliary components attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    # Consumables
    consumables: List[GasBottle] = Field(
        default_factory=list,
        title="Consumable(s)",
        description="Consumables inside the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    # Materials
    substances: List[Substance] = Field(
        default_factory=list,
        title="Substance(s)",
        description="Substances inside the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    single_crystals: List[Crystal] = Field(
        default_factory=list,
        title="Crystal(s)",
        description="Crystals inside the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    wafer_samples: List[WaferSample] = Field(
        default_factory=list,
        title="Wafer sample(s)",
        description="Wafer samples inside the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    # Accessories
    tip_sensors: List[Component] = Field(
        default_factory=list,
        title="Tip sensor(s)",
        description="Tip sensors attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    accessories: List[Component] = Field(
        default_factory=list,
        title="Accessories",
        description="Other accessories attached to the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    # Logbook
    logbook_entries: List[Component] = Field(
        default_factory=list,
        title="Logbook entries",
        description="Logbook entries of the instrument.",
        metadata={"type": "SAMPLE", "multivalue": True},
    )

    @classmethod
    def get_code(cls) -> str:
        return "ISTM"

    @classmethod
    def get_label(cls) -> str:
        return "Instrument.STM"


class Code(OpenBISObject):
    version: str = Field(
        default="",
        title="Version",
        description="Version of the code",
        metadata={"type": "VARCHAR"},
    )
    filepath_executable: str = Field(
        default="",
        title="Filepath executable",
        description="File path to the executable",
        metadata={"type": "VARCHAR"},
    )
    repository_url: str = Field(
        default="",
        title="Repository URL",
        description="URL of the code repository",
        metadata={"type": "VARCHAR"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "CODE"

    @classmethod
    def get_label(cls) -> str:
        return "Code"


class Software(OpenBISObject):
    version: str = Field(
        default=None,
        title="Version",
        description="Software version",
        metadata={"type": "VARCHAR"},
    )
    url: str = Field(
        default=None,
        title="Software URL",
        description="Software URL",
        metadata={"type": "VARCHAR"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "SOFT"

    @classmethod
    def get_label(cls) -> str:
        return "Software"


class Simulation(OpenBISObject):
    wfms_uuid: str = Field(
        default=None,
        title="WFMS UUID",
        description="Workflow management system UUID",
        metadata={"type": "VARCHAR"},
    )


class AtomisticModel(Simulation):
    cell: Dict = Field(
        default_factory=dict,
        title="Cell",
        description="Dictionary describing the simulation cell",
        metadata={"type": "JSON"},
    )
    dimensionality: int = Field(
        default=0,
        title="Dimensionality",
        description="Dimensionality of the model (e.g., 1D, 2D, 3D)",
        metadata={"type": "INTEGER"},
    )
    periodic_boundary_conditions: List[bool] = Field(
        default_factory=lambda: [False, False, False],
        title="PBC",
        min_length=3,
        max_length=3,
        description="Periodic boundary conditions for x, y, z directions",
        metadata={"type": "BOOLEAN", "multivalue": True},
    )
    volume: float = Field(
        default=0.0,
        title="Volume",
        description="Volume of the simulation cell",
        metadata={"type": "REAL"},
    )
    crystal_concepts: List[CrystalConcept] = Field(
        default_factory=list,
        title="Crystal concept(s)",
        description="List of crystal concepts in the model",
        metadata={"type": "PARENT"},
    )
    geometry_optimisation: "GeometryOptimisation" = Field(
        default=None,
        title="Geometry optimisation",
        description="Geometry optimization settings",
        metadata={"type": "PARENT"},
    )
    molecules: List[Molecule] = Field(
        default_factory=list,
        title="Molecule(s)",
        description="List of molecules in the model",
        metadata={"type": "PARENT"},
    )
    reaction_product_concepts: List[ReactionProductConcept] = Field(
        default_factory=list,
        title="Reaction product concept(s)",
        description="List of reaction product concepts",
        metadata={"type": "PARENT"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "ATMO"

    @classmethod
    def get_label(cls) -> str:
        return "Atomistic Model"


class BandStructure(Simulation):
    band_gap: EnergyValue = Field(
        default=None,
        title="Band gap",
        description="Band gap energy value",
        metadata={"type": "JSON"},
    )
    level_theory_method: str = Field(
        default="",
        title="Level of theory (method)",
        description="Method used for level of theory calculations",
        metadata={"type": "VARCHAR"},
    )
    level_theory_parameters: Dict = Field(
        default_factory=dict,
        title="Level of theory (parameters)",
        description="Parameters for the level of theory method",
        metadata={"type": "JSON"},
    )
    input_parameters: Dict = Field(
        default_factory=dict,
        title="Input parameters",
        description="Input parameters for the simulation",
        metadata={"type": "JSON"},
    )
    output_parameters: Dict = Field(
        default_factory=dict,
        title="Output parameters",
        description="Output parameters from the simulation",
        metadata={"type": "JSON"},
    )
    atomistic_models: List["AtomisticModel"] = Field(
        default_factory=list,
        title="Atomistic model(s)",
        description="List of atomistic models",
        metadata={"type": "PARENT"},
    )
    codes: List[Code] = Field(
        default_factory=list,
        title="Code(s)",
        description="List of codes used in the band structure calculation",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    aiida_node: "AiidaNode" = Field(
        default_factory=list,
        title="AiiDA archive",
        description="Main AiiDA node containing AiiDA archive file",
        metadata={"type": "SAMPLE", "multivalue": False},
    )

    @classmethod
    def get_code(cls) -> str:
        return "BAND"

    @classmethod
    def get_label(cls) -> str:
        return "Band Structure"


class GeometryOptimisation(Simulation):
    cell_opt_constraints: str = Field(
        default=None,
        title="Cell opt constraints",
        description="Constraints applied to the cell optimisation",
        metadata={"type": "VARCHAR"},
    )
    cell_optimised: bool = Field(
        default=None,
        title="Cell optimised",
        description="Whether the cell was optimised",
        metadata={"type": "BOOLEAN"},
    )
    driver_code: str = Field(
        default=None,
        title="Driver code",
        description="Driver code used for the simulation",
        metadata={"type": "VARCHAR"},
    )
    constrained: bool = Field(
        default=None,
        title="Constrained",
        description="Whether the simulation is constrained",
        metadata={"type": "BOOLEAN"},
    )
    force_convergence_threshold: EnergyDensityValue = Field(
        default=None,
        title="Force convergence threshold",
        description="Force convergence threshold value",
        metadata={"type": "JSON"},
    )
    level_theory_method: str = Field(
        default=None,
        title="Level of theory (method)",
        description="Method for the level of theory",
        metadata={"type": "VARCHAR"},
    )
    level_theory_parameters: Dict = Field(
        default_factory=dict,
        title="Level of theory (parameters)",
        description="Parameters for the level of theory method",
        metadata={"type": "JSON"},
    )
    input_parameters: Dict = Field(
        default_factory=dict,
        title="Input parameters",
        description="Input parameters for the simulation",
        metadata={"type": "JSON"},
    )
    output_parameters: Dict = Field(
        default_factory=dict,
        title="Output parameters",
        description="Output parameters from the simulation",
        metadata={"type": "JSON"},
    )
    atomistic_models: List["AtomisticModel"] = Field(
        default_factory=list,
        title="Atomistic model(s)",
        description="List of atomistic models",
        metadata={"type": "PARENT"},
    )
    codes: List[Code] = Field(
        default_factory=list,
        title="Code(s)",
        description="List of codes used",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    aiida_node: "AiidaNode" = Field(
        default_factory=list,
        title="AiiDA archive",
        description="Main AiiDA node containing AiiDA archive file",
        metadata={"type": "SAMPLE", "multivalue": False},
    )

    @classmethod
    def get_code(cls) -> str:
        return "GEOP"

    @classmethod
    def get_label(cls) -> str:
        return "Geometry Optimisation"


class MeanFieldHubbard(OpenBISObject):
    charge: int = Field(
        default=None, title="Charge", description="Charge", metadata={"type": "INTEGER"}
    )
    convergence_coefficient: float = Field(
        default=None,
        title="Convergence coefficient",
        description="Convergence coefficient",
        metadata={"type": "REAL"},
    )
    density_tolerance: float = Field(
        default=None,
        title="Density tolerance",
        description="Density tolerance",
        metadata={"type": "REAL"},
    )
    down_densities: List[int] = Field(
        default_factory=list,
        title="Down densities",
        description="Down densities",
        metadata={"type": "INTEGER", "multivalue": True},
    )
    down_electrons: List[int] = Field(
        default_factory=list,
        title="Down electrons",
        description="Down electrons",
        metadata={"type": "INTEGER", "multivalue": True},
    )
    number_k_points: int = Field(
        default=None,
        title="Number of k points",
        description="Number of k-points",
        metadata={"type": "INTEGER"},
    )
    on_site_hubbard_repulsion_value: EnergyValue = Field(
        default=None,
        title="On-site Hubbard repulsion U value",
        description="Hubbard U value",
        metadata={"type": "JSON"},
    )
    up_densities: List[int] = Field(
        default_factory=list,
        title="Up densities",
        description="Up densities",
        metadata={"type": "INTEGER", "multivalue": True},
    )
    up_electrons: List[int] = Field(
        default_factory=list,
        title="Up electrons",
        description="Up electrons",
        metadata={"type": "INTEGER", "multivalue": True},
    )
    atomistic_models: List[AtomisticModel] = Field(
        default_factory=list,
        title="Atomistic model(s)",
        description="Atomistic models",
        metadata={"type": "PARENT"},
    )
    aiida_node: "AiidaNode" = Field(
        default_factory=list,
        title="AiiDA archive",
        description="Main AiiDA node containing AiiDA archive file",
        metadata={"type": "SAMPLE", "multivalue": False},
    )

    @classmethod
    def get_code(cls) -> str:
        return "MFHU"

    @classmethod
    def get_label(cls) -> str:
        return "Mean Field Hubbard"


class MinimumEnergyPotential(OpenBISObject):
    energies: List[EnergyValue] = Field(
        default_factory=list,
        title="Energies",
        description="List of energy values",
        metadata={"type": "JSON"},
    )
    energy_barrier: EnergyValue = Field(
        default=None,
        title="Energy barrier",
        description="Energy barrier value",
        metadata={"type": "JSON"},
    )
    geometry_constraints: List[float] = Field(
        default_factory=list,
        title="Geometry constraints",
        description="Geometry constraints",
        metadata={"type": "REAL", "multivalue": True},
    )
    geometry_constraints_increments: List[float] = Field(
        default_factory=list,
        title="Geometry constraints increments",
        description="Geometry constraints increments",
        metadata={"type": "REAL", "multivalue": True},
    )
    method_type: PathFindingMethodEnum = Field(
        default=None,
        title="Method type",
        description="Method type",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    number_geometries: int = Field(
        default=None,
        title="Number of geometries",
        description="Number of geometries",
        metadata={"type": "INTEGER"},
    )
    atomistic_models: List[AtomisticModel] = Field(
        default_factory=list,
        title="Atomistic model(s)",
        description="List of atomistic models",
        metadata={"type": "PARENT"},
    )
    aiida_node: "AiidaNode" = Field(
        default_factory=list,
        title="AiiDA archive",
        description="Main AiiDA node containing AiiDA archive file",
        metadata={"type": "SAMPLE", "multivalue": False},
    )

    @classmethod
    def get_code(cls) -> str:
        return "MEPO"

    @classmethod
    def get_label(cls) -> str:
        return "Minimum Energy Potential"


class PDOS(Simulation):
    level_theory_method: str = Field(
        default="",
        title="Level of theory (method)",
        description="Method used for level of theory calculations",
        metadata={"type": "VARCHAR"},
    )
    level_theory_parameters: Dict = Field(
        default_factory=dict,
        title="Level of theory (parameters)",
        description="Parameters for the level of theory method",
        metadata={"type": "JSON"},
    )
    input_parameters: Dict = Field(
        default_factory=dict,
        title="Input parameters",
        description="Input parameters for the simulation",
        metadata={"type": "JSON"},
    )
    output_parameters: Dict = Field(
        default_factory=dict,
        title="Output parameters",
        description="Output parameters from the simulation",
        metadata={"type": "JSON"},
    )
    atomistic_models: List["AtomisticModel"] = Field(
        default_factory=list,
        title="Atomistic model(s)",
        description="List of atomistic models",
        metadata={"type": "PARENT"},
    )
    codes: List[Code] = Field(
        default_factory=list,
        title="Code(s)",
        description="List of codes used in the PDOS calculation",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    aiida_node: "AiidaNode" = Field(
        default_factory=list,
        title="AiiDA archive",
        description="Main AiiDA node containing AiiDA archive file",
        metadata={"type": "SAMPLE", "multivalue": False},
    )

    @classmethod
    def get_code(cls) -> str:
        return "PDOS"

    @classmethod
    def get_label(cls) -> str:
        return "PDOS"


class UnclassifiedSimulation(Simulation):
    input_parameters: Dict = Field(
        default_factory=dict,
        title="Input parameters",
        description="Input parameters for the simulation",
        metadata={"type": "JSON"},
    )
    output_parameters: Dict = Field(
        default_factory=dict,
        title="Output parameters",
        description="Output parameters from the simulation",
        metadata={"type": "JSON"},
    )
    atomistic_models: List["AtomisticModel"] = Field(
        default_factory=list,
        title="Atomistic model(s)",
        description="List of atomistic models",
        metadata={"type": "PARENT"},
    )
    codes: List[Code] = Field(
        default_factory=list,
        title="Code(s)",
        description="List of codes used in the simulation",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    aiida_node: "AiidaNode" = Field(
        default_factory=list,
        title="AiiDA archive",
        description="Main AiiDA node containing AiiDA archive file",
        metadata={"type": "SAMPLE", "multivalue": False},
    )

    @classmethod
    def get_code(cls) -> str:
        return "UNSM"

    @classmethod
    def get_label(cls) -> str:
        return "Unclassified Simulation"


class VibrationalSpectroscopy(Simulation):
    level_theory_method: str = Field(
        default="",
        title="Level of theory (method)",
        description="Method used for level of theory calculations",
        metadata={"type": "VARCHAR"},
    )
    level_theory_parameters: Dict = Field(
        default_factory=dict,
        title="Level of theory (parameters)",
        description="Parameters for the level of theory method",
        metadata={"type": "JSON"},
    )
    input_parameters: Dict = Field(
        default_factory=dict,
        title="Input parameters",
        description="Input parameters for the simulation",
        metadata={"type": "JSON"},
    )
    output_parameters: Dict = Field(
        default_factory=dict,
        title="Output parameters",
        description="Output parameters from the simulation",
        metadata={"type": "JSON"},
    )
    atomistic_models: List["AtomisticModel"] = Field(
        default_factory=list,
        title="Atomistic model(s)",
        description="List of atomistic models",
        metadata={"type": "PARENT"},
    )
    codes: List[Code] = Field(
        default_factory=list,
        title="Code(s)",
        description="List of codes used in the vibrational spectroscopy calculation",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    aiida_node: "AiidaNode" = Field(
        default_factory=list,
        title="AiiDA archive",
        description="Main AiiDA node containing AiiDA archive file",
        metadata={"type": "SAMPLE", "multivalue": False},
    )

    @classmethod
    def get_code(cls) -> str:
        return "VBSP"

    @classmethod
    def get_label(cls) -> str:
        return "Vibrational Spectroscopy"


class PotentialEnergyCalculation(Simulation):
    energy: EnergyValue = Field(
        default=None,
        title="Energy",
        description="Energy value",
        metadata={"type": "JSON"},
    )
    level_theory_method: str = Field(
        default="",
        title="Level of theory (method)",
        description="Method used for level of theory calculations",
        metadata={"type": "VARCHAR"},
    )
    level_theory_parameters: Dict = Field(
        default_factory=dict,
        title="Level of theory (parameters)",
        description="Parameters for the level of theory method",
        metadata={"type": "JSON"},
    )
    input_parameters: Dict = Field(
        default_factory=dict,
        title="Input parameters",
        description="Input parameters for the simulation",
        metadata={"type": "JSON"},
    )
    output_parameters: Dict = Field(
        default_factory=dict,
        title="Output parameters",
        description="Output parameters from the simulation",
        metadata={"type": "JSON"},
    )
    atomistic_models: List["AtomisticModel"] = Field(
        default_factory=list,
        title="Atomistic model(s)",
        description="List of atomistic models",
        metadata={"type": "PARENT"},
    )
    codes: List[Code] = Field(
        default_factory=list,
        title="Code(s)",
        description="List of codes used in the potential energy calculation",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    aiida_node: "AiidaNode" = Field(
        default_factory=list,
        title="AiiDA archive",
        description="Main AiiDA node containing AiiDA archive file",
        metadata={"type": "SAMPLE", "multivalue": False},
    )

    @classmethod
    def get_code(cls) -> str:
        return "PECA"

    @classmethod
    def get_label(cls) -> str:
        return "Potential Energy Calculation"


class Action(OpenBISObject):
    duration: str = Field(
        default="0 00:00:00",
        title="Duration",
        description="Duration of the action in format 'days hh:mm:ss'",
        metadata={"type": "VARCHAR"},
    )
    component: Component = Field(
        default=None,
        title="Component",
        description="Component used in the action",
        metadata={"type": "SAMPLE"},
    )
    component_settings: Dict = Field(
        default_factory=dict,
        title="Component settings",
        description="Settings for the component. The keys are the names of the component properties that are used in the specific observable type and the values are the properties values.",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "ACTN"

    @classmethod
    def get_label(cls) -> str:
        return "Action"

    @field_validator("duration")
    @classmethod
    def validate_duration_format(cls, v):
        # Pattern for "days hh:mm:ss" format
        pattern = r"^\d+\s+([01]?\d|2[0-3]):([0-5]?\d):([0-5]?\d)$"
        if not re.match(pattern, v):
            raise ValueError(
                'Duration must be in format "days hh:mm:ss" (e.g., "1 12:30:45")'
            )
        return v


class Annealing(Action):
    target_temperature: TemperatureValue = Field(
        default=None,
        title="Target temperature",
        description="Target temperature for the annealing process",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "HEAT"

    @classmethod
    def get_label(cls) -> str:
        return "Annealing"


class Coating(Action):
    @classmethod
    def get_code(cls) -> str:
        return "COAT"

    @classmethod
    def get_label(cls) -> str:
        return "Coating"


class Cooldown(Action):
    target_temperature: TemperatureValue = Field(
        default=None,
        title="Target temperature",
        description="Target temperature for the cooldown process",
        metadata={"type": "JSON"},
    )
    cryogen: str = Field(
        default="",
        title="Cryogen",
        description="Name of the used cryogen",
        metadata={"type": "VARCHAR"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "COOL"

    @classmethod
    def get_label(cls) -> str:
        return "Cooldown"


class Delamination(Action):
    @classmethod
    def get_code(cls) -> str:
        return "DELA"

    @classmethod
    def get_label(cls) -> str:
        return "Delamination"


class Deposition(Action):
    substrate_temperature: TemperatureValue = Field(
        default=None,
        title="Substrate temperature",
        description="Temperature of the substrate during deposition",
        metadata={"type": "JSON"},
    )
    substance: Substance = Field(
        default=None,
        title="Substance",
        description="Substance being deposited",
        metadata={"type": "SAMPLE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "DEPO"

    @classmethod
    def get_label(cls) -> str:
        return "Deposition"


class Dosing(Action):
    gas: Substance = Field(
        default=None,
        title="Dosing gas",
        description="Gas used for dosing",
        metadata={"type": "SAMPLE"},
    )
    pressure: PressureValue = Field(
        default=None,
        title="Pressure",
        description="Pressure during dosing",
        metadata={"type": "JSON"},
    )
    substrate_temperature: TemperatureValue = Field(
        default=None,
        title="Substrate temperature",
        description="Substrate temperature during dosing",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "GASD"

    @classmethod
    def get_label(cls) -> str:
        return "Dosing"


class Etching(Action):
    @classmethod
    def get_code(cls) -> str:
        return "ETCH"

    @classmethod
    def get_label(cls) -> str:
        return "Etching"


class Fishing(Action):
    @classmethod
    def get_code(cls) -> str:
        return "FISH"

    @classmethod
    def get_label(cls) -> str:
        return "Fishing"


class FieldEmission(Action):
    @classmethod
    def get_code(cls) -> str:
        return "FIEM"

    @classmethod
    def get_label(cls) -> str:
        return "Field Emission"


class LightIrradiation(Action):
    @classmethod
    def get_code(cls) -> str:
        return "LITE"

    @classmethod
    def get_label(cls) -> str:
        return "Light Irradiation"


class MechanicalPressing(Action):
    @classmethod
    def get_code(cls) -> str:
        return "MEPR"

    @classmethod
    def get_label(cls) -> str:
        return "Mechanical Pressing"


class Rinse(Action):
    @classmethod
    def get_code(cls) -> str:
        return "RINS"

    @classmethod
    def get_label(cls) -> str:
        return "Rinse"


class Sputtering(Action):
    sputter_ion: str = Field(
        default=None,
        title="Ion",
        description="Ion used for sputtering",
        metadata={"type": "VARCHAR"},
    )
    pressure: PressureValue = Field(
        default=None,
        title="Pressure",
        description="Pressure during sputtering",
        metadata={"type": "JSON"},
    )
    current: CurrencyValue = Field(
        default=None,
        title="Current",
        description="Current applied during sputtering",
        metadata={"type": "JSON"},
    )
    angle: AngleValue = Field(
        default=None,
        title="Angle",
        description="Angle of sputtering",
        metadata={"type": "JSON"},
    )
    substrate_temperature: TemperatureValue = Field(
        default=None,
        title="Substrate temperature",
        description="Substrate temperature during sputtering",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "IONB"

    @classmethod
    def get_label(cls) -> str:
        return "Sputtering"


class Room(OpenBISObject):
    organisation: Organisation = Field(
        default=None,
        title="Organisation",
        description="Organisation associated with the location",
        metadata={"type": "SAMPLE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "ROOM"

    @classmethod
    def get_label(cls) -> str:
        return "Room"


class Analysis(OpenBISObject):
    codes: List[Code] = Field(
        default_factory=list,
        title="Code(s)",
        description="List of codes used in the analysis",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    measurements: List["MeasurementSession"] = Field(
        default_factory=list,
        title="Measurement(s)",
        description="List of measurement sessions used in the analysis",
        metadata={"type": "PARENT"},
    )
    software: List[Software] = Field(
        default_factory=list,
        title="Software",
        description="List of software used in the analysis",
        metadata={"type": "SAMPLE", "multivalue": True},
    )

    @classmethod
    def get_code(cls) -> str:
        return "ANLS"

    @classmethod
    def get_label(cls) -> str:
        return "Analysis"


class Result(OpenBISObject):
    analysis: List[Analysis] = Field(
        default_factory=list,
        title="Analysis",
        description="List of analysis",
        metadata={"type": "PARENT"},
    )
    simulations: List[
        Union[BandStructure, GeometryOptimisation, PDOS, VibrationalSpectroscopy]
    ] = Field(
        default_factory=list,
        title="Simulation(s)",
        description="List of simulations",
        metadata={"type": "PARENT"},
    )
    measurements: List["MeasurementSession"] = Field(
        default_factory=list,
        title="Measurement(s)",
        description="List of associated measurement sessions",
        metadata={"type": "PARENT"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "RESL"

    @classmethod
    def get_label(cls) -> str:
        return "Result"


class Draft(OpenBISObject):
    draft_type: DraftTypeEnum = Field(
        default=None,
        title="Draft type",
        description="Type of the draft",
        metadata={"type": "CONTROLLEDVOCABULARY"},
    )
    results: List[Result] = Field(
        default_factory=list,
        title="Result(s)",
        description="List of associated results",
        metadata={"type": "PARENT"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "DRFT"

    @classmethod
    def get_label(cls) -> str:
        return "Draft"


class AiidaNode(OpenBISObject):
    wfms_uuid: str = Field(
        default=None,
        title="WFMS UUID",
        description="Workflow management system UUID",
        metadata={"type": "VARCHAR"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "ADND"

    @classmethod
    def get_label(cls) -> str:
        return "Aiida Node"


class Observable(OpenBISObject):
    channel_name: str = Field(
        default=None,
        title="Channel name",
        description="Name of the reading channel",
        metadata={"type": "VARCHAR"},
    )
    component: Component = Field(
        default=None,
        title="Component",
        description="Used component",
        metadata={"type": "SAMPLE"},
    )
    component_settings: Dict = Field(
        default_factory=dict,
        title="Component settings",
        description="Settings for the component. The keys are the names of the component properties that are used in the specific observable type and the values are the properties values.",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "OBSV"

    @classmethod
    def get_label(cls) -> str:
        return "Observable"


class CurrentObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "CURR"

    @classmethod
    def get_label(cls) -> str:
        return "Current Observable"


class ElementalCompositionObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "ELEM"

    @classmethod
    def get_label(cls) -> str:
        return "Elemental Composition Observable"


class FluxObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "FLUX"

    @classmethod
    def get_label(cls) -> str:
        return "Flux Observable"


class ForceObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "FORC"

    @classmethod
    def get_label(cls) -> str:
        return "Force Observable"


class InductanceObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "INDU"

    @classmethod
    def get_label(cls) -> str:
        return "Inductance Observable"


class PHValueObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "PHVA"

    @classmethod
    def get_label(cls) -> str:
        return "pH Value Observable"


class PressureObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "PRES"

    @classmethod
    def get_label(cls) -> str:
        return "Pressure Observable"


class ResistanceObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "RESI"

    @classmethod
    def get_label(cls) -> str:
        return "Resistance Observable"


class SpeedObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "SPED"

    @classmethod
    def get_label(cls) -> str:
        return "Speed Observable"


class TemperatureObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "TEMP"

    @classmethod
    def get_label(cls) -> str:
        return "Temperature Observable"


class VoltageObservable(Observable):
    @classmethod
    def get_code(cls) -> str:
        return "VOLT"

    @classmethod
    def get_label(cls) -> str:
        return "Voltage Observable"


class STMSimulation(Simulation):
    level_theory_method: str = Field(
        default="",
        title="Level of theory (method)",
        description="Method used for level of theory calculations",
        metadata={"type": "VARCHAR"},
    )
    level_theory_parameters: Dict = Field(
        default_factory=dict,
        title="Level of theory (parameters)",
        description="Parameters for the level of theory method",
        metadata={"type": "JSON"},
    )
    input_parameters: Dict = Field(
        default_factory=dict,
        title="Input parameters",
        description="Input parameters for the simulation",
        metadata={"type": "JSON"},
    )
    output_parameters: Dict = Field(
        default_factory=dict,
        title="Output parameters",
        description="Output parameters from the simulation",
        metadata={"type": "JSON"},
    )
    codes: List[Code] = Field(
        default_factory=list,
        title="Code(s)",
        description="List of codes used in the band structure calculation",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    aiida_node: "AiidaNode" = Field(
        default_factory=list,
        title="AiiDA archive",
        description="Main AiiDA node containing AiiDA archive file",
        metadata={"type": "SAMPLE", "multivalue": False},
    )
    p_tip: str = Field(
        default=None,
        title="P-tip",
        description="P-tip",
        metadata={"type": "REAL"},
    )
    bias_voltages: Dict = Field(
        default_factory=dict,
        title="Bias voltage",
        description="Bias voltage",
        metadata={"type": "JSON"},
    )
    isovalues: Dict = Field(
        default_factory=dict,
        title="Isovalues",
        description="Isovalues",
        metadata={"type": "JSON"},
    )
    heights: Dict = Field(
        default_factory=dict,
        title="Heights",
        description="Heights",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "STMS"

    @classmethod
    def get_label(cls) -> str:
        return "STM Simulation"


class MeasurementSession(OpenBISObject):
    measurement_folder_path: str = Field(
        default=None,
        title="Measurement folder path",
        description="Path to the measurement folder",
        metadata={"type": "VARCHAR"},
    )
    measurement_session: "MeasurementSession" = Field(
        default=None,
        title="Measurement session",
        description="Reference to another measurement session",
        metadata={"type": "PARENT"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "MSSE"

    @classmethod
    def get_label(cls) -> str:
        return "Measurement Session"


class SPMMeasurement(OpenBISObject):
    pass
    # @classmethod
    # def get_code(cls) -> str:
    #     return "MICR"

    # @classmethod
    # def get_label(cls) -> str:
    #     return "SPM Measurement"


class RamanMeasurement(OpenBISObject):
    pass
    # @classmethod
    # def get_code(cls) -> str:
    #     return "RAMA"

    # @classmethod
    # def get_label(cls) -> str:
    #     return "Raman Measurement"


class PhotoelectronSpectroscopy(OpenBISObject):
    pass
    # @classmethod
    # def get_code(cls) -> str:
    #     return "PHES"

    # @classmethod
    # def get_label(cls) -> str:
    #     return "Photoelectron Spectroscopy"


class OpticalMicroscopy(OpenBISObject):
    pass
    # @classmethod
    # def get_code(cls) -> str:
    #     return "OPTI"

    # @classmethod
    # def get_label(cls) -> str:
    #     return "Optical Microscopy"


# class Maintenance(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "MAIN"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Maintenance"


# class ErrorsProblems(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "ERRO"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Errors and Problems"


# class Status(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "STAT"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Status"


# class CalibrationOptimisaton(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "CALI"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Calibration Optimisation"


# class CryogenFilling(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "CRYF"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Cryostat Filling"


# class ChangeLocation(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "LOCA"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Change Location"

# class ChangeProperty(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "PROP"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Change Property"


# class Degasing(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "DEGA"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Degasing"


# class Bakeout(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "BAKE"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Bakeout"


# class Comment(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "COMM"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Comment"


# class Cleaning(OpenBISObject):
#     @classmethod
#     def get_code(cls) -> str:
#         return "CLEA"

#     @classmethod
#     def get_label(cls) -> str:
#         return "Cleaning"


class Process(OpenBISObject):
    short_name: str = Field(
        default=None,
        title="Short name",
        description="Short name for the process",
        metadata={"type": "VARCHAR"},
    )
    instrument: Optional[Union[Instrument, InstrumentSTM]] = Field(
        default=None,
        title="Instrument",
        description="Instrument used for the process",
        metadata={"type": "SAMPLE"},
    )
    process_steps_settings: List[ProcessStepSettings] = Field(
        default_factory=list,
        title="Process steps settings",
        description="Settings for each process step",
        metadata={"type": "JSON"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "PROC"

    @classmethod
    def get_label(cls) -> str:
        return "Process"


class ProcessStep(OpenBISObject):
    actions: List[Action] = Field(
        default_factory=list,
        title="Action(s)",
        description="List of actions performed in this step",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    observables: List[Observable] = Field(
        default_factory=list,
        title="Observable(s)",
        description="List of observables recorded in this step",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    instrument: Optional[Union[Instrument, InstrumentSTM]] = Field(
        default=None,
        title="Instrument",
        description="Instrument used for this step",
        metadata={"type": "SAMPLE"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "PRST"

    @classmethod
    def get_label(cls) -> str:
        return "Process Step"


class Preparation(OpenBISObject):
    process_steps: List[ProcessStep] = Field(
        default_factory=list,
        title="Process step(s)",
        description="List of process steps",
        metadata={"type": "CHILDREN"},
    )

    @classmethod
    def get_code(cls) -> str:
        return "PREP"

    @classmethod
    def get_label(cls) -> str:
        return "Preparation"


class Publication(OpenBISObject):
    abstract: str = Field(
        default=None,
        title="Abstract",
        description="Abstract of the publication",
        metadata={"type": "VARCHAR"},
    )
    doi: str = Field(
        default=None,
        title="DOI",
        description="DOI of the publication",
        metadata={"type": "VARCHAR"},
    )
    url: str = Field(
        default=None,
        title="URL",
        description="URL of the publication",
        metadata={"type": "VARCHAR"},
    )
    dataset_url: str = Field(
        default=None,
        title="Dataset URL",
        description="URL to the associated dataset",
        metadata={"type": "VARCHAR"},
    )
    year: int = Field(
        default=None,
        title="Year",
        description="Year of publication",
        metadata={"type": "INTEGER"},
    )
    authors: List[Author] = Field(
        default_factory=list,
        title="Author(s)",
        description="List of authors",
        metadata={"type": "SAMPLE", "multivalue": True},
    )
    drafts: List[Draft] = Field(
        default_factory=list,
        title="Draft(s)",
        description="Related drafts",
        metadata={"type": "PARENT"},
    )
    grants: List[Grant] = Field(
        default_factory=list,
        title="Grant(s)",
        description="Grants supporting the publication",
        metadata={"type": "SAMPLE", "multivalue": True},
    )

    @classmethod
    def get_code(cls) -> str:
        return "PUBL"

    @classmethod
    def get_label(cls) -> str:
        return "Publication"


AllowedTypes = Union[Publication, Preparation, Person]


class InstanceTypes(BaseModel):
    types: List[AllowedTypes]


def get_all_openbis_subclasses(cls=OpenBISObject):
    subclasses = set()
    for subclass in cls.__subclasses__():
        subclasses.add(subclass)
        subclasses.update(get_all_openbis_subclasses(subclass))
    return subclasses


OpenBISUnion = Union[tuple(get_all_openbis_subclasses())]


class OpenBISInstance(BaseModel):
    instance: OpenBISUnion


# print(OpenBISInstance.schema_json(indent = 4))
