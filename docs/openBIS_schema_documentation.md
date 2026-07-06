# openBIS Data Model Documentation

## 1. Object Types

### 2D Layer Material
* **Code:** `2D_LAYER_MATERIAL`
* **Generated code prefix:** `TDLM`
* **Semantic Annotation:**
* **Metadata:** `{'type': 'slab'}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `supplier_own_name` | Supplier own name | Supplier own name | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

#### Section: Material Composition & Structure

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `top_layer_material` | Top Layer Material | Top layer material | VARCHAR | False | False | False | |
| `layer_count` | Number of layers | Number of layers | VARCHAR | False | False | False |
| `impurities` | Impurities | Impurities | VARCHAR | False | False | False |
| `heterostructure_stack` | Heterostructure Stack | Heterostructure Stack | XML | False | False | False |  | `{'custom_widget': 'Spreadsheet'}`
| `substrate` | Substrate | Substrate | VARCHAR | False | False | False |
| `sample_plate` | Sample Plate | Sample Plate | VARCHAR | False | False | False |

#### Section: Synthesis & Origin

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `growth_method` | Growth/Fabrication Method | Growth/Fabrication method | VARCHAR | False | False | False | |
| `synthesised_by` | Synthesised by | Synthesised by | VARCHAR | False | False | False |
| `supplier` | Supplier | Supplier | OBJECT (All) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |  |

#### Section: Dimensions

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `shape` | Shape | Shape | CONTROLLEDVOCABULARY (SHAPE_ENUM) | False | False | False | |
| `diameter_mm` | Diameter [mm] | Diameter [mm] | REAL | False | False | False |
| `height_mm` | Height [mm] | Height [mm] | REAL | False | False | False |
| `width_mm` | Width [mm] | Width [mm] | REAL | False | False | False |  |
| `thickness_mm` | Thickness [mm] | Thickness [mm] | REAL | False | False | False |  |

#### Section: Storage & Location

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `special_storage_conditions` | Special Storage Conditions | Special storage conditions | CONTROLLEDVOCABULARY (SPECIALSTORAGECONDITIONSENUM) | False | True | False | |
| `package_opening_date` | Package opening date | Package opening date | DATE | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |

### 6-Fold Evaporator
* **Code:** `6_FOLD_EVAPORATOR`
* **Generated code prefix:** `6FEV`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `main_category` | Main category | Main category | CONTROLLEDVOCABULARY (COMPONENTMAINCATEGORYENUM) | False | False | False |
| `sub_category` | Sub category | Sub category | CONTROLLEDVOCABULARY (COMPONENTSUBCATEGORYENUM) | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `slot_number` | Slot number | Slot number | INTEGER | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

#### Section: Settings

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `target_temperature_k` | Target Temperature [K] | Target temperature [K] | REAL | False | False | False | |
| `p_value` | P value | P value | REAL | False | False | False |
| `i_value` | I value | I value | REAL | False | False | False |
| `ep_percentage` | EP (%) | EP (%) | REAL | False | False | False |  |

### 6-Fold Evaporator Settings
* **Code:** `6_FOLD_EVAPORATOR_SETTINGS`
* **Generated code prefix:** `6FST`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `target_temperature_k` | Target Temperature [K] | Target temperature [K] | REAL | False | False | False | |
| `p_value` | P value | P value | REAL | False | False | False |
| `i_value` | I value | I value | REAL | False | False | False |
| `ep_percentage` | EP (%) | EP (%) | REAL | False | False | False |  |

### Action
* **Code:** `ACTION`
* **Generated code prefix:** `ACTN`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '⚙️', 'type': 'action'}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

#### Section: Component & Settings

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `components_names` | Component(s) name(s) | Component(s) name(s) | VARCHAR | False | True | False |
| `components_settings_values` | Component(s) settings values | Component(s) settings values | VARCHAR | False | True | False |

### AFM Sensor
* **Code:** `AFM_SENSOR`
* **Generated code prefix:** `AFMS`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `main_category` | Main category | Main category | CONTROLLEDVOCABULARY (COMPONENTMAINCATEGORYENUM) | False | False | False |
| `sub_category` | Sub category | Sub category | CONTROLLEDVOCABULARY (COMPONENTSUBCATEGORYENUM) | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

#### Section: Technical specifications

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `fabrication_method` | Fabrication method | Fabrication method | VARCHAR | False | False | False |
| `fabrication_date` | Fabrication date | Fabrication date | DATE | False | False | False |
| `resonance_frequency_hz` | Resonance frequency [Hz] | Resonance frequency [Hz] | REAL | False | False | False | |

#### Section: Storage & Location

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `location` | Location | Location | OBJECT (All) | False | False | False |

### Aiida Node
* **Code:** `AIIDA_NODE`
* **Generated code prefix:** `ADND`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `wfms_uuid` | WFMS UUID | WFMS UUID | VARCHAR | False | False | False |

### Analyser
* **Code:** `ANALYSER`
* **Generated code prefix:** `ANLS`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `main_category` | Main category | Main category | CONTROLLEDVOCABULARY (COMPONENTMAINCATEGORYENUM) | False | False | False |
| `sub_category` | Sub category | Sub category | CONTROLLEDVOCABULARY (COMPONENTSUBCATEGORYENUM) | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

#### Section: Settings

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `density_g_cm3` | Density [g/cm3] | Density [g/cm3] | REAL | False | False | False | |

### Analyser Settings
* **Code:** `ANALYSER_SETTINGS`
* **Generated code prefix:** `ANST`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `density_g_cm3` | Density [g/cm3] | Density [g/cm3] | REAL | False | False | False | |

### Analysis
* **Code:** `ANALYSIS`
* **Generated code prefix:** `ANLY`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

### Annealing
* **Code:** `ANNEALING`
* **Generated code prefix:** `HEAT`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '🔥', 'type': 'action'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `pbn_stage` | PBN Stage | PBN Stage | OBJECT (PBN_STAGE) | False | False | False |
| `pbn_stage_settings` | PBN Stage Settings | PBN Stage Settings | OBJECT (PBN_STAGE_SETTINGS) | False | False | False |
| `dc_evaporator` | DC Evaporator | DC Evaporator | OBJECT (DC_EVAPORATOR) | False | False | False |
| `dc_evaporator_settings` | DC Evaporator Settings | DC Evaporator Settings | OBJECT (DC_EVAPORATOR_SETTINGS) | False | False | False |

### Atomistic Model
* **Code:** `ATOMISTIC_MODEL`
* **Generated code prefix:** `ATMO`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `wfms_uuid` | WFMS UUID | WFMS UUID | VARCHAR | False | False | False |
| `cell` | Cell | Cell | JSON | False | False | False |
| `dimensionality` | Dimensionality | Dimensionality | INTEGER | False | False | False |
| `periodic_boundary_conditions` | PBC | PBC | BOOLEAN | False | True | False |
| `volume` | Volume | Volume | REAL | False | False | False |

### Author
* **Code:** `AUTHOR`
* **Generated code prefix:** `AUTH`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `person` | Person | Person | OBJECT (All) | False | False | False |
| `affiliations` | Affiliation(s) | Affiliation(s) | OBJECT (All) | False | True | False |

### 🔥 Bakeout
* **Code:** `BAKEOUT_LOGENTRY`
* **Generated code prefix:** `BAKEOUTLOG`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'LOGBOOK_COLLECTION', 'color': '#e67800', 'icon': '🔥', 'type': 'BAKEOUT_LOGENTRY'}`

#### Section: GeneralInfo

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `description` | Description | Description | VARCHAR | False | False | False |
| `valid_from` | Valid From | Valid From | VARCHAR | False | False | False |
| `ilog_logbook` | ILOG_LOGBOOK | This is the iLog logbook entry identifier. | BOOLEAN | False | False | False |
| `name` | Name | Name | VARCHAR | False | False | False |
| `document` | Document | Document | MULTILINE_VARCHAR | False | False | False | | `{'custom_widget': 'Word Processor'}`

### Band Structure
* **Code:** `BAND_STRUCTURE`
* **Generated code prefix:** `BAND`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `wfms_uuid` | WFMS UUID | WFMS UUID | VARCHAR | False | False | False |
| `band_gap` | Band gap | Description | VARCHAR | False | False | False |
| `level_theory_method` | Level of theory (method) | Level of theory (method) | VARCHAR | False | False | False |
| `level_theory_parameters` | Level of theory (parameters) | Level of theory (parameters) | JSON | False | False | False |
| `input_parameters` | Input parameters | Input parameters | JSON | False | False | False |
| `output_parameters` | Output parameters | Output parameters | JSON | False | False | False |
| `codes` | Code(s) | Code(s) | OBJECT (All) | False | True | False |
| `aiida_node` | AiiDA archive | AiiDA archive | OBJECT (All) | False | False | False | |

### ⚙️ Calibration & Optimization
* **Code:** `CALIBRATION_OPTIMIZATION_LOGENTRY`
* **Generated code prefix:** `CALIBRATIONOPTIMIZATIONLOG`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'LOGBOOK_COLLECTION', 'color': '#40cd54', 'icon': '⚙️', 'type': 'CALIBRATION_OPTIMIZATION_LOGENTRY'}`

#### Section: GeneralInfo

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `description` | Description | Description | VARCHAR | False | False | False |
| `valid_from` | Valid From | Valid From | VARCHAR | False | False | False |
| `ilog_logbook` | ILOG_LOGBOOK | This is the iLog logbook entry identifier. | BOOLEAN | False | False | False |
| `name` | Name | Name | VARCHAR | False | False | False |
| `document` | Document | Document | MULTILINE_VARCHAR | False | False | False | | `{'custom_widget': 'Word Processor'}`

### Chamber
* **Code:** `CHAMBER`
* **Generated code prefix:** `CHBR`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `main_category` | Main category | Main category | CONTROLLEDVOCABULARY (COMPONENTMAINCATEGORYENUM) | False | False | False |
| `sub_category` | Sub category | Sub category | CONTROLLEDVOCABULARY (COMPONENTSUBCATEGORYENUM) | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

### 🧼 Cleaning
* **Code:** `CLEANING_LOGENTRY`
* **Generated code prefix:** `CLEANINGLOG`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'LOGBOOK_COLLECTION', 'color': '#dcbe28', 'icon': '🧼', 'type': 'CLEANING_LOGENTRY'}`

#### Section: GeneralInfo

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `description` | Description | Description | VARCHAR | False | False | False |
| `valid_from` | Valid From | Valid From | VARCHAR | False | False | False |
| `ilog_logbook` | ILOG_LOGBOOK | This is the iLog logbook entry identifier. | BOOLEAN | False | False | False |
| `name` | Name | Name | VARCHAR | False | False | False |
| `document` | Document | Document | MULTILINE_VARCHAR | False | False | False | | `{'custom_widget': 'Word Processor'}`

### Coating
* **Code:** `COATING`
* **Generated code prefix:** `COAT`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '🧥', 'type': 'action'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `components_names` | Component(s) name(s) | Component(s) name(s) | VARCHAR | False | True | False |
| `components_settings_values` | Component(s) settings values | Component(s) settings values | VARCHAR | False | True | False |

### Code
* **Code:** `CODE`
* **Generated code prefix:** `CODE`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `version` | Version | Version | VARCHAR | False | False | False |
| `filepath_executable` | Filepath executable | Filepath executable | VARCHAR | False | False | False |
| `repository_url` | Repository URL | Repository URL | VARCHAR | False | False | False |

### 💬 Comment
* **Code:** `COMMENT_LOGENTRY`
* **Generated code prefix:** `COMMENTLOG`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'LOGBOOK_COLLECTION', 'color': '#aa78c8', 'icon': '💬', 'type': 'COMMENT_LOGENTRY'}`

#### Section: GeneralInfo

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `description` | Description | Description | VARCHAR | False | False | False |
| `valid_from` | Valid From | Valid From | VARCHAR | False | False | False |
| `ilog_logbook` | ILOG_LOGBOOK | This is the iLog logbook entry identifier. | BOOLEAN | False | False | False |
| `name` | Name | Name | VARCHAR | False | False | False |
| `document` | Document | Document | MULTILINE_VARCHAR | False | False | False | | `{'custom_widget': 'Word Processor'}`

### Component
* **Code:** `COMPONENT`
* **Generated code prefix:** `COMP`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `main_category` | Main category | Main category | CONTROLLEDVOCABULARY (COMPONENTMAINCATEGORYENUM) | False | False | False |
| `sub_category` | Sub category | Sub category | CONTROLLEDVOCABULARY (COMPONENTSUBCATEGORYENUM) | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

### Cooldown
* **Code:** `COOLDOWN`
* **Generated code prefix:** `COOL`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '❄️', 'type': 'action'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `cryostat` | Cryostat | Cryostat | OBJECT (CRYOSTAT) | False | False | False |
| `cryostat_settings` | Cryostat Settings | Cryostat Settings | OBJECT (CRYOSTAT_SETTINGS) | False | False | False |

### ❄️ Cryogen Filling
* **Code:** `CRYOGEN_FILLING_LOGENTRY`
* **Generated code prefix:** `CRYOGENFILLINGLOG`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'LOGBOOK_COLLECTION', 'color': '#005aaa', 'icon': '❄️', 'type': 'CRYOGEN_FILLING_LOGENTRY'}`

#### Section: GeneralInfo

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `description` | Description | Description | VARCHAR | False | False | False |
| `valid_from` | Valid From | Valid From | VARCHAR | False | False | False |
| `ilog_logbook` | ILOG_LOGBOOK | This is the iLog logbook entry identifier. | BOOLEAN | False | False | False |
| `name` | Name | Name | VARCHAR | False | False | False |
| `cryogen` | Cryogen | Cryogen | VARCHAR | False | False | False |
| `weight_before_kg` | Weight Before [kg] | Weight Before [kg] | REAL | False | False | False |
| `weight_after_kg` | Weight After [kg] | Weight After [kg] | REAL | False | False | False |
| `document` | Document | Document | MULTILINE_VARCHAR | False | False | False | | `{'custom_widget': 'Word Processor'}`
| `dewar` | Dewar | Dewar | VARCHAR | False | False | False |

### Cryostat
* **Code:** `CRYOSTAT`
* **Generated code prefix:** `CRYO`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `main_category` | Main category | Main category | CONTROLLEDVOCABULARY (COMPONENTMAINCATEGORYENUM) | False | False | False |
| `sub_category` | Sub category | Sub category | CONTROLLEDVOCABULARY (COMPONENTSUBCATEGORYENUM) | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

#### Section: Settings

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `target_temperature_k` | Target Temperature [K] | Target Temperature [K] | REAL | False | False | False | |
| `cryogen` | Cryogen | Cryogen | VARCHAR | False | False | False | |

### Cryostat Settings
* **Code:** `CRYOSTAT_SETTINGS`
* **Generated code prefix:** `CRST`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `target_temperature_k` | Target Temperature [K] | Target Temperature [K] | REAL | False | False | False | |
| `cryogen` | Cryogen | Cryogen | VARCHAR | False | False | False | |

### Crystal
* **Code:** `CRYSTAL`
* **Generated code prefix:** `CRRE`
* **Semantic Annotation:**
* **Metadata:** `{'type': 'slab'}`

#### Parents
| Object Type| Minimum | Maximum |
| :--- | :--- | :--- |
| CRYSTAL_CONCEPT | 1 | 1 |

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `barcode` | Custom Barcode | Custom Barcode | VARCHAR | False | False | False |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `face` | Face | Face | VARCHAR | False | False | False |
| `material` | Material | Material | VARCHAR | False | False | False |
| `sample_plate` | Sample plate | Sample plate | VARCHAR | False | False | False |
| `diameter_mm` | Diameter [mm] | Diameter [mm] | REAL | False | False | False |
| `length_mm` | Length [mm] | Length [mm] | REAL | False | False | False |
| `width_mm` | Width [mm] | Width [mm] | REAL | False | False | False |
| `thickness_mm` | Thickness [mm] | Thickness [mm] | REAL | False | False | False |
| `screw_material` | Screw material | Screw material | VARCHAR | False | False | False |
| `shape` | Shape | Shape | CONTROLLEDVOCABULARY (SHAPE_ENUM) | False | False | False |
| `reference_number` | Reference number | Reference number | VARCHAR | False | False | False |
| `current_location` | Current location | Current location (Temporary. It should be replaced by Location in the meantime.) | MULTILINE_VARCHAR | False | False | False | | `{'custom_widget': 'Word Processor'}`
| `special_storage_conditions` | Special storage condition(s) | Special storage condition(s) | CONTROLLEDVOCABULARY (SPECIALSTORAGECONDITIONSENUM) | False | True | False |
| `package_opening_date` | Package opening date | Package opening date | DATE | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `supplier` | Supplier | Supplier | OBJECT (All) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `synthesised_by` | Synthesised by | Synthesised by | OBJECT (All) | False | True | False |
| `supplier_own_name` | Supplier own name | Supplier own name | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

### Crystal Concept
* **Code:** `CRYSTAL_CONCEPT`
* **Generated code prefix:** `CRCO`
* **Semantic Annotation:**
* **Metadata:** `{'type': 'slab_concept'}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `face` | Face | Face | VARCHAR | False | False | False |
| `material` | Material | Material | VARCHAR | False | False | False |
| `lattice_parameters_angstrom` | Lattice parameters [Angstrom] | Lattice parameters [Angstrom] | VARCHAR | False | True | False |
| `crystal_space_group` | Crystal space group | Crystal space group | INTEGER | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

### DC Evaporator
* **Code:** `DC_EVAPORATOR`
* **Generated code prefix:** `DCEV`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `main_category` | Main category | Main category | CONTROLLEDVOCABULARY (COMPONENTMAINCATEGORYENUM) | False | False | False |
| `sub_category` | Sub category | Sub category | CONTROLLEDVOCABULARY (COMPONENTSUBCATEGORYENUM) | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

#### Section: Settings

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `current_a` | Current [A] | Current [A] | REAL | False | False | False | |
| `voltage_v` | Voltage [V] | Voltage [V] | REAL | False | False | False | |

### DC Evaporator Settings
* **Code:** `DC_EVAPORATOR_SETTINGS`
* **Generated code prefix:** `DCST`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `current_a` | Current [A] | Current [A] | REAL | False | False | False | |
| `voltage_v` | Voltage [V] | Voltage [V] | REAL | False | False | False | |

### 💨 Degasing
* **Code:** `DEGASING_LOGENTRY`
* **Generated code prefix:** `DEGASINGLOG`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'LOGBOOK_COLLECTION', 'color': '#009678', 'icon': '💨', 'type': 'DEGASING_LOGENTRY'}`

#### Section: GeneralInfo

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `description` | Description | Description | VARCHAR | False | False | False |
| `valid_from` | Valid From | Valid From | VARCHAR | False | False | False |
| `ilog_logbook` | ILOG_LOGBOOK | This is the iLog logbook entry identifier. | BOOLEAN | False | False | False |
| `name` | Name | Name | VARCHAR | False | False | False |
| `molecule` | Molecule | Molecule | OBJECT (MOLECULE) | False | False | False |
| `temperature_celsius` | Temperature [Celsius] | Temperature [Celsius] | REAL | False | False | False |
| `duration` | Duration | Duration | REAL | False | False | False |
| `document` | Document | Document | MULTILINE_VARCHAR | False | False | False | | `{'custom_widget': 'Word Processor'}`

### Delamination
* **Code:** `DELAMINATION`
* **Generated code prefix:** `DELA`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '🧩', 'type': 'action'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `components_names` | Component(s) name(s) | Component(s) name(s) | VARCHAR | False | True | False |
| `components_settings_values` | Component(s) settings values | Component(s) settings values | VARCHAR | False | True | False |

### Deposition
* **Code:** `DEPOSITION`
* **Generated code prefix:** `DEPO`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '🧱', 'type': 'action'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `substance` | Substance | Substance | OBJECT (SUBSTANCE) | False | False | False |
| `6_fold_evaporator` | 6-Fold Evaporator | 6-Fold Evaporator | OBJECT (6_FOLD_EVAPORATOR) | False | False | False |
| `6_fold_evaporator_settings` | 6-Fold Evaporator Settings | 6-Fold Evaporator Settings | OBJECT (6_FOLD_EVAPORATOR_SETTINGS) | False | False |False |
| `dc_evaporator` | DC Evaporator | DC Evaporator | OBJECT (DC_EVAPORATOR) | False | False | False |
| `dc_evaporator_settings` | DC Evaporator Settings | DC Evaporator Settings | OBJECT (DC_EVAPORATOR_SETTINGS) | False | False | False |

### Device Substrate
* **Code:** `DEVICE_SUBSTRATE`
* **Generated code prefix:** `DVSB`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `special_storage_conditions` | Special storage condition(s) | Special storage condition(s) | CONTROLLEDVOCABULARY (SPECIALSTORAGECONDITIONSENUM) | False | True | False |
| `sample_plate` | Sample plate | Sample plate | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `supplier` | Supplier | Supplier | OBJECT (All) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `synthesised_by` | Synthesised by | Synthesised by | OBJECT (All) | False | True | False |
| `supplier_own_name` | Supplier own name | Supplier own name | VARCHAR | False | False | False |

### Dewar
* **Code:** `DEWAR`
* **Generated code prefix:** `DWAR`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `cryogen` | Cryogen | Cryogen | VARCHAR | False | False | False |
| `current_weight_kg` | Current weight [kg] | Current weight [kg] | REAL | False | False | False |
| `tara_weight_kg` | Tara weight [kg] | Tara weight [kg] | REAL | False | False | False |

### Dosing
* **Code:** `DOSING`
* **Generated code prefix:** `GASD`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '💧', 'type': 'action'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `gas_bottle` | Dosing gas | Dosing gas | OBJECT (GAS_BOTTLE) | False | False | False |
| `valve` | Valve | Valve | OBJECT (VALVE) | False | False | False |
| `valve_settings` | Valve settings | Valve settings | OBJECT (VALVE_SETTINGS) | False | False | False |

### Draft
* **Code:** `DRAFT`
* **Generated code prefix:** `DRFT`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `draft_type` | Draft type | Draft type | CONTROLLEDVOCABULARY (DRAFTTYPEENUM) | False | False | False |

### Electronics
* **Code:** `ELECTRONICS`
* **Generated code prefix:** `ELTR`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `main_category` | Main category | Main category | CONTROLLEDVOCABULARY (COMPONENTMAINCATEGORYENUM) | False | False | False |
| `sub_category` | Sub category | Sub category | CONTROLLEDVOCABULARY (COMPONENTSUBCATEGORYENUM) | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

### ⚠️ Errors & Problems
* **Code:** `ERRORS_AND_PROBLEMS_LOGENTRY`
* **Generated code prefix:** `ERRORSANDPROBLEMSLOG`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'LOGBOOK_COLLECTION', 'color': '#b8131d', 'icon': '⚠️', 'type': 'ERRORS_AND_PROBLEMS_LOGENTRY'}`

#### Section: GeneralInfo

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `description` | Description | Description | VARCHAR | False | False | False |
| `valid_from` | Valid From | Valid From | VARCHAR | False | False | False |
| `ilog_logbook` | ILOG_LOGBOOK | This is the iLog logbook entry identifier. | BOOLEAN | False | False | False |
| `name` | Name | Name | VARCHAR | False | False | False |
| `document` | Document | Document | MULTILINE_VARCHAR | False | False | False | | `{'custom_widget': 'Word Processor'}`

### Etching
* **Code:** `ETCHING`
* **Generated code prefix:** `ETCH`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '📌', 'type': 'action'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `components_names` | Component(s) name(s) | Component(s) name(s) | VARCHAR | False | True | False |
| `components_settings_values` | Component(s) settings values | Component(s) settings values | VARCHAR | False | True | False |

### Field Emission
* **Code:** `FIELD_EMISSION`
* **Generated code prefix:** `FIEM`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '⚡', 'type': 'action'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `components_names` | Component(s) name(s) | Component(s) name(s) | VARCHAR | False | True | False |
| `components_settings_values` | Component(s) settings values | Component(s) settings values | VARCHAR | False | True | False |

### Filament
* **Code:** `FILAMENT`
* **Generated code prefix:** `FILA`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |

### Fishing
* **Code:** `FISHING`
* **Generated code prefix:** `FISH`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '🎣', 'type': 'action'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `components_names` | Component(s) name(s) | Component(s) name(s) | VARCHAR | False | True | False |
| `components_settings_values` | Component(s) settings values | Component(s) settings values | VARCHAR | False | True | False |

### Gas Bottle
* **Code:** `GAS_BOTTLE`
* **Generated code prefix:** `GASB`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `chemical_formula` | Chemical Formula | Chemical Formula | VARCHAR | False | False | False |
| `amount_mg` | Amount [mg] | Amount [mg] | VARCHAR | False | False | False |
| `amount_ml` | Amount [ml] | Amount [ml] | VARCHAR | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `special_storage_conditions` | Special storage condition(s) | Special storage condition(s) | CONTROLLEDVOCABULARY (SPECIALSTORAGECONDITIONSENUM) | False | True | False |
| `package_opening_date` | Package opening date | Package opening date | DATE | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `supplier` | Supplier | Supplier | OBJECT (All) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

### Geometry Optimisation
* **Code:** `GEOMETRY_OPTIMISATION`
* **Generated code prefix:** `GEOP`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `wfms_uuid` | WFMS UUID | WFMS UUID | VARCHAR | False | False | False |
| `cell_opt_constraints` | Cell optimisation constraints | Cell optimisation constraints | VARCHAR | False | False | False |
| `cell_optimised` | Cell optimised | Cell optimised | BOOLEAN | False | False | False |
| `driver_code` | Driver code | Driver code | VARCHAR | False | False | False |
| `constrained` | Constrained | Constrained | BOOLEAN | False | False | False |
| `force_convergence_threshold` | Force convergence threshold | Force convergence threshold | JSON | False | False | False |
| `level_theory_method` | Level of theory (method) | Level of theory (method) | VARCHAR | False | False | False |
| `level_theory_parameters` | Level of theory (parameters) | Level of theory (parameters) | JSON | False | False | False |
| `input_parameters` | Input parameters | Input parameters | JSON | False | False | False |
| `output_parameters` | Output parameters | Output parameters | JSON | False | False | False |
| `codes` | Code(s) | Code(s) | OBJECT (All) | False | True | False |
| `aiida_node` | AiiDA archive | AiiDA archive | OBJECT (All) | False | False | False | |

### Grant
* **Code:** `GRANT`
* **Generated code prefix:** `GRNT`
* **Semantic Annotation:**
* **Metadata:**

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `acronym` | Acronym | Acronym | VARCHAR | False | False | False |
| `funding_scheme` | Funding scheme | Funding scheme | VARCHAR | False | False | False |
| `budget_value` | Budget (value) | Budget (value) | REAL | False | False | False |
| `budget_currency` | Budget (currency) | Budget (currency) | CONTROLLEDVOCABULARY (BUDGET_CURRENCY_ENUM) | False | False | False |
| `project_id` | Project ID | Project ID | VARCHAR | False | False | False |
| `acknowledgement_sentence` | Acknowledgement sentence | Acknowledgement sentence | MULTILINE_VARCHAR | False | False | False |
| `start_date` | Start date | Start date | DATE | False | False | False |
| `end_date` | End date | End date | DATE | False | False | False |
| `funder_name` | Funder name | Funder name | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

### Group
* **Code:** `GROUP`
* **Generated code prefix:** `GROP`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `organisation` | Organisation | Organisation | OBJECT (All) | False | False | False |

### Instrument
* **Code:** `INSTRUMENT`
* **Generated code prefix:** `ISTR`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'INSTRUMENT_COLLECTION', 'ilog': true, 'type': 'instrument'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `responsibles` | Responsible(s) | Responsible(s) | OBJECT (PERSON) | False | False | False |


### Instrument STM
* **Code:** `INSTRUMENT.STM`
* **Generated code prefix:** `ISTM`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'INSTRUMENT_COLLECTION', 'ilog': true, 'type': 'instrument'}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `responsibles` | Responsible(s) | Responsible(s) | OBJECT (PERSON) | False | False | False |

#### Section: Components

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `pumps` | Pump(s) | Pump(s) | OBJECT (All) | False | True | False |
| `gauges` | Gauge(s) | Gauge(s) | OBJECT (All) | False | True | False |
| `vacuum_chambers` | Vacuum chamber(s) | Vacuum chamber(s) | OBJECT (All) | False | True | False |
| `ports_valves` | Port(s)/Valve(s) | Port(s)/Valve(s) | OBJECT (All) | False | True | False |
| `preparation_tools` | Preparation tool(s) | Preparation tool(s) | OBJECT (All) | False | True | False |
| `analysers` | Analyser(s) | Analyser(s) | OBJECT (All) | False | True | False |
| `mechanical_components` | Mechanical component(s) | Mechanical component(s) | OBJECT (All) | False | True | False |
| `stm_components` | STM component(s) | STM component(s) | OBJECT (All) | False | True | False |
| `control_data_acquisition` | Control and data acquisition component(s) | Control and data acquisition component(s) | OBJECT (All) | False | True | False |
| `temperature_environment_control` | Temperature and environment control component(s) | Temperature and environment control component(s) | OBJECT (All) | False | False | False |
| `auxiliary_components` | Auxiliary component(s) | Auxiliary component(s) | OBJECT (All) | False | True | False |

#### Section: Materials

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `substances` | Substance(s) | Substance(s) | OBJECT (SUBSTANCE) | False | True | False |
| `crystals` | Crystal(s) | Crystal(s) | OBJECT (CRYSTAL) | False | True | False |
| `wafer_samples` | Wafer sample(s) | Wafer sample(s) | OBJECT (All) | False | True | False |

#### Section: Accessories

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `tip_sensors` | Tip sensor(s) | Tip sensor(s) | OBJECT (All) | False | True | False |
| `consumables` | Consumable(s) | Consumable(s) | OBJECT (All) | False | True | False |

### Ion Gauge
* **Code:** `ION_GAUGE`
* **Generated code prefix:** `IONG`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `main_category` | Main category | Main category | CONTROLLEDVOCABULARY (COMPONENTMAINCATEGORYENUM) | False | False | False |
| `sub_category` | Sub category | Sub category | CONTROLLEDVOCABULARY (COMPONENTSUBCATEGORYENUM) | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

#### Section: Settings

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `filament_current_a` | Filament current [A] | Filament current [A] | REAL | False | False | False | |
| `filament` | Filament | Filament | VARCHAR | False | False | False | |

### Ion Gauge Settings
* **Code:** `ION_GAUGE_SETTINGS`
* **Generated code prefix:** `IONG`
* **Semantic Annotation:**
* **Metadata:**

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `filament_current_a` | Filament current [A] | Filament current [A] | REAL | False | False | False | |
| `filament` | Filament | Filament | VARCHAR | False | False | False | |

### Ion Pump
* **Code:** `ION_PUMP`
* **Generated code prefix:** `IONP`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'COMPONENT_COLLECTION', 'ilog': true}`

#### Section: General information

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `main_category` | Main category | Main category | CONTROLLEDVOCABULARY (COMPONENTMAINCATEGORYENUM) | False | False | False |
| `sub_category` | Sub category | Sub category | CONTROLLEDVOCABULARY (COMPONENTSUBCATEGORYENUM) | False | False | False |
| `model` | Model | Model | VARCHAR | False | False | False |
| `serial_number` | Serial number | Serial number | VARCHAR | False | False | False |
| `empa_id` | Empa ID | Empa ID | VARCHAR | False | False | False |
| `object_status` | Object type | Object type | CONTROLLEDVOCABULARY (OBJECTSTATUSENUM) | False | False | False |
| `receive_date` | Receive date | Receive date | DATE | False | False | False |
| `manufacturer` | Manufacturer | Manufacturer | OBJECT (All) | False | False | False |
| `location` | Location | Location | OBJECT (All) | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |

### Light Irradiation
* **Code:** `LIGHT_IRRADIATION`
* **Generated code prefix:** `LITE`
* **Semantic Annotation:**
* **Metadata:** `{'icon': '💡', 'type': 'action'}`

#### Section:

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | Name | VARCHAR | False | False | False |
| `description` | Description | Description | VARCHAR | False | False | False |
| `comments` | Comments | Comments | VARCHAR | False | False | False |
| `duration` | Duration | Duration | VARCHAR | False | False | False |
| `components_names` | Component(s) name(s) | Component(s) name(s) | VARCHAR | False | True | False |
| `components_settings_values` | Component(s) settings values | Component(s) settings values | VARCHAR | False | True | False |

### 🔧 Maintenance
* **Code:** `MAINTENANCE_LOGENTRY`
* **Generated code prefix:** `MAINTENANCELOG`
* **Semantic Annotation:**
* **Metadata:** `{'collectionType': 'LOGBOOK_COLLECTION', 'color': '#966e3c', 'icon': '🔧', 'type': 'MAINTENANCE_LOGENTRY'}`

#### Section: GeneralInfo

| Property Code | Label | Description | Datatype | Mandatory | Multivalued | Unique | Semantic Annotation | Metadata
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `description` | Description | Description | VARCHAR | False | False | False |
| `valid_from` | Valid From | Valid From | VARCHAR | False | False | False |
| `ilog_logbook` | ILOG_LOGBOOK | This is the iLog logbook entry identifier. | BOOLEAN | False | False | False |
| `name` | Name | Name | VARCHAR | False | False | False |
| `document` | Document | Document | MULTILINE_VARCHAR | False | False | False | | `{'custom_widget': 'Word Processor'}`

---

## 2. Data Set Types

### DAT dataset

* **Code:** `DAT_DATASET`

#### Section:

| Property Code | Label | Datatype | Mandatory | Multivalued | Unique | Description | Semantic Annotation
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | VARCHAR | False | False | False | Name |  |
| `description` | Description | VARCHAR | False | False | False | Description |  |
| `comments` | Comments | VARCHAR | False | False | False | Comments |  |

### Observable

* **Code:** `OBSERVABLE`

#### Section:

| Property Code | Label | Datatype | Mandatory | Multivalued | Unique | Description | Semantic Annotation
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | VARCHAR | False | False | False | Name |  |
| `description` | Description | VARCHAR | False | False | False | Description |  |
| `comments` | Comments | VARCHAR | False | False | False | Comments |  |

### SXM dataset

* **Code:** `SXM_DATASET`

#### Section:

| Property Code | Label | Datatype | Mandatory | Multivalued | Unique | Description | Semantic Annotation
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| `name` | Name | VARCHAR | False | False | False | Name |  |
| `description` | Description | VARCHAR | False | False | False | Description |  |
| `comments` | Comments | VARCHAR | False | False | False | Comments |  |

---

## 3. Vocabulary Types

### Budget currency

* **Code:** `BUDGET_CURRENCY_ENUM`

| Term Code | Label | Description |
| :--- | :--- | :--- |
| CHF | CHF | Swiss Franc
| EUR | EUR | Euro
| USD | USD | US Dollar

### Component - Main Category
* **Code:** `COMPONENTMAINCATEGORYENUM`

| Term Code | Label | Description |
| :--- | :--- | :--- |
| AUXILIARY | Auxiliary |
| MICROSCOPE_CORE_COMPONENTS | Microscope Core Components |
| SAMPLE_PREPARATION_HANDLING | Sample Preparation & Handling |
| VACUUM_SYSTEM | Vacuum System |

### Component - Sub Category
* **Code:** `COMPONENTSUBCATEGORYENUM`

| Term Code | Label | Description |
| :--- | :--- | :--- |
| ANALYSER | Analyser |
| AUXILIARY | Auxiliary |
| CONTROL_DATA_ACQUISITION | Control & Data Acquisition |
| GAUGE | Gauge |
| MECHANICAL_COMPONENT | Mechanical Component |
| PREPARATION_TOOLS | Preparation Tools |
| PUMP | Pump |
| STM | Scanning Tunneling Microscope |
| TEMPERATURE_ENVIRONMENT_CONTROL | Temperature & Environment Control |
| VACUUM_CHAMBER | Vacuum System |

### Default collection views
* **Code:** `DEFAULT_COLLECTION_VIEWS`

| Term Code | Label | Description |
| :--- | :--- | :--- |
| FORM_VIEW | Form view |
| IMAGING_GALLERY_VIEW | Imaging Gallery view | Imaging gallery view for collections
| LIST_VIEW | List view |

### Default dataset views
* **Code:** `DEFAULT_DATASET_VIEWS`

| Term Code | Label | Description |
| :--- | :--- | :--- |
| IMAGING_DATASET_VIEWER | Imaging dataset viewer | Imaging viewer type for dataset

### Default object views
* **Code:** `DEFAULT_OBJECT_VIEWS`

| Term Code | Label | Description |
| :--- | :--- | :--- |
| IMAGING_DATASET_VIEWER | Imaging dataset viewer | Imaging viewer type for data
| IMAGING_GALLERY_VIEW | Imaging Gallery view | Imaging gallery viewer for objects

### Draft type
* **Code:** `DRAFTTYPEENUM`

| Term Code | Label | Description |
| :--- | :--- | :--- |
| POSTPRINT | Postprint |
| PREPRINT | Preprint |

### ILog base types
* **Code:** `ILOG_BASE_TYPES`

| Term Code | Label | Description |
| :--- | :--- | :--- |
| COMPONENT | Component |
| INSTRUMENT | Instrument |

### Vocabulary for tagging imaging previews
* **Code:** `IMAGING_TAGS`

| Term Code | Label | Description |
| :--- | :--- | :--- |
| DAT | dat | dat chart
| GOOD_MEAS | + | +
| PAPER_MEAS | ++ | ++
| SPECTRA | spectra | spectra locator image
| SPECTRUM | spectrum | spectrum
| STML | STML | STML image
| SXM | sxm | sxm image
| THZSTML | THz-STML | THz-STML image

### nanotech@surfaces subgroups
* **Code:** `NANOTECHSURFACESSUBGROUPENUM`

| Term Code | Label | Description |
| :--- | :--- | :--- |
| ATOMISTIC_SIMULATIONS | Atomistic Simulations |
| CARBON_NANOMATERIALS | Carbon Nanomaterials |
| CHIRAL_SURFACES | Chiral Surfaces |
| MATERIALS_TO_DEVICES | Materials to Devices |
| QUANTUM_MAGNETISM | Quantum Magnetism |
| RESEARCH_INFRASTRUCTURE | Research Infrastructure |
| RESEARCH_MANAGEMENT | Research Management |
| TWO_D_QUANTUM_MATERIALS | Two-Dimensional Quantum Materials |

### Object Status
* **Code:** `OBJECTSTATUSENUM`

| Term Code | Label | Description
| :--- | :--- | :---
| ACTIVE | Active |
| BROKEN | Broken |
| DISPOSED | Disposed |
| INACTIVE | Inactive |

### Path Finding Method
* **Code:** `PATHFINDINGMETHODENUM`

| Term Code | Label | Description
| :--- | :--- | :---
| NEB | Nudged Elastic Band |
| STRING | String Method |

### Shape
* **Code:** `SHAPE_ENUM`

| Term Code | Label | Description
| :--- | :--- | :---
| CYLINDRICAL | Cylindrical | Cyclindrical
| RECTANGULAR | Rectangular | Rectangular
| ROUND | Round | Round

### Special Storage Conditions
* **Code:** `SPECIALSTORAGECONDITIONSENUM`

| Term Code | Label | Description
| :--- | :--- | :---
| DARK | Dark |
| DRY | Dry |
| FLAMMABLE | Flammable |
| FREEZER | Freezer |
| FRIDGE | Fridge |
| NO_OXYGEN | No Oxygen |
| POISONOUS | Poisonous | Poisonous

### Work Status
* **Code:** `WORKSTATUSENUM`

| Term Code | Label | Description
| :--- | :--- | :---
| ACTIVE | Active |
| INACTIVE | Inactive |
