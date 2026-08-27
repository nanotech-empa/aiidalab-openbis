# New Group Blueprint: Configuring openBIS for Process Constructor

To onboard a new research group and enable the **Process Constructor** application in openBIS, three foundational entity types must be defined: **Actions**, **Instruments**, and **Components**.

Understanding the relational hierarchy among these entities is essential:
* **Instruments** represent physical apparatuses, setups, or laboratory spaces.
* **Components** are modular tools, sub-units, or physical methods belonging to an instrument.
* **Actions** define operational workflows that utilize specific materials, components, and parameter settings.

---

## 1. Instruments

**Instruments** are the primary physical equipment, apparatuses, or laboratory workspaces where samples are prepared, processed, and analyzed.

* **Hierarchy & Structure:** An instrument acts as a parent container composed of one or more **Components**.
* **Requirement:** An instrument must be defined before its components can be assigned. If a component is not linked to an instrument, it cannot be selected within the Process Constructor.
* **Definition Interface:** Instruments must be registered in openBIS via the **iLog** interface by the research group responsible for them.
* **Examples:**
  * `THz-STM` (contains vacuum chambers, multi-pocket evaporators, sample stages)
  * `Wet Chemistry Lab` (contains hotplates, spin coaters, sonicators, pipettes)

---

## 2. Components & Component Settings

**Components** are functional tools, sub-units, or manual methods associated with an instrument to execute specific actions on samples.

* **Assignment:** A component must belong to exactly one instrument at any given time (though it can be reassigned to a different instrument if physical equipment is moved).
* **Definition Interface:** Components are registered via the **iLog** interface by the responsible research group.
* **Settings Requirement:** Every component must have a corresponding **Component Settings Object Type** defined in openBIS. This object captures runtime parameters (e.g., *Temperature*, *Pressure*, *Rotation Speed*, *Deposition Rate*).
* **Examples:**
  * `6-Fold Evaporator` → Settings: *Crucible Position*, *Filament Current*, *Target Temperature*
  * `By Hand` (manual operation) → Settings: *Operator Notes*, *Tool Type/Size*

---

## 3. Actions

**Actions** are individual operational procedures performed on samples during experimental workflows.

* **Process Steps & Parallelism:** Actions always exist within a **Process Step**. A single process step can contain multiple actions executed concurrently (in parallel).
* **openBIS Admin Metadata Configuration:** In the openBIS Admin UI, under the Object Type **Metadata** configuration, the group administrator must define two mandatory key-value pairs:
  * `icon` → A string representing the display icon (e.g., `⚙️`, `🔥`, `🧼`).
  * `type` → A string identifying the entity type as an action (i.e., `action`).
* **Component Association Rule:** For an action to support a specific component in the Process Constructor, the Action Type **must** explicitly define properties for both:
  1. The **Component** (Sample/Object link)
  2. The corresponding **Component Settings** (Sample/Object link or embedded structure)

  *Note: If either property is missing from the Action Type definition, that component cannot be used for the action within the Process Constructor interface.*
* **Runtime Flexibility:** Registering components and settings on an action definition establishes available capabilities. During an experimental run, researchers can select and configure only the specific components utilized.

---

## 4. Action Structure & Schema Reference

To define an action, include properties covering core metadata, consumables, and all supported components/settings pairs.

### Standard Action Properties

| Property Category | Field Name | Type / Format | Description |
| :--- | :--- | :--- | :--- |
| **Admin Metadata** | `type` | Key-Value Metadata | Must be set to `action` |
| | `icon` | Key-Value Metadata | Display icon string (e.g., `⚙️`, `🔥`, `🧼`) |
| **Object Properties** | `Name` | `VARCHAR` | Identifier of the action (e.g., *Thermal Evaporation*, *Spin Coating*) |
| | `Description` | `MULTILINE_VARCHAR` | Detailed procedure overview or protocol guidelines |
| | `Comments` | `MULTILINE_VARCHAR` | Runtime remarks, deviations, or operator notes |
| | `Duration` | `VARCHAR` | Execution duration (e.g., in DD HH:MM:SS format) |
| **Materials** | `Used Materials` | `SAMPLE` | Consumables, active substances, or solutions used (e.g., *Gas Bottle*, *Substance*) |
| **Component Pair 1** | `[Component A]` | `SAMPLE` | Reference to the component entity |
| | `[Component A] Settings` | `SAMPLE` | Associated parameter settings object |
| **Component Pair 2** | `[Component B]` | `SAMPLE` | Reference to an alternative component entity |
| | `[Component B] Settings` | `SAMPLE` | Associated parameter settings object |

---

### Concrete Action Example: *Deposition*

A generic deposition action supporting multiple hardware configurations contains the following configuration:

* **Admin Metadata:** `type: action`, `icon: 🔥`
* **Properties:**
  * `Name`
  * `Description`
  * `Comments`
  * `Duration`
  * `Substance` (Used Material)
  * `By Hand` & `By Hand Settings`
  * `6-Fold Evaporator` & `6-Fold Evaporator Settings`
  * `DC Evaporator` & `DC Evaporator Settings`

---

## 5. Setup Checklist for New Groups

1. **Define Instruments:** Register all physical setups, apparatuses, and labs in the **iLog** interface.
2. **Define Components & Settings Types:**
   - Register each component in **iLog** and assign it to its parent instrument.
   - Create corresponding `[Component] Settings` object types with relevant operational parameters.
3. **Configure Action Types:**
   - In openBIS Admin UI, set Object Type metadata key-values (`type: action`, `icon: <emoji/string>`).
   - Create standard properties (`Name`, `Description`, `Comments`, `Duration`, `Used Materials`).
   - Add property pairs (`<Component>` and `<Component> Settings`) for each tool supported by that action.
4. **Deploy to Process Constructor:** Verify that actions, instruments, and modular components resolve properly in the visual workflow builder.
