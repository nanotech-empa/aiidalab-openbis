# AiiDAlab-openBIS App User Guide

## 1. Overview & App Structure

The **AiiDAlab-openBIS** application (`0_home.ipynb`) provides an integrated interface between AiiDAlab and openBIS for managing microscopy experiments, sample lifecycles, and raw data synchronisation.

The main page is organized into the following tabs:

- **Experiments**
  - **Sample preparation** (`1_sample_preparation.ipynb`): Register starting samples, record sequential preparation steps, parallel actions, and real-time observables, or save reusable process templates.
  - **Sample measurement** (`2_sample_measurement.ipynb`): Configure and manage background watchdogs that monitor local AiiDAlab directories, parse new measurement files (e.g., Nanonis SPM files), and upload them to openBIS.
  - **Folder synchronisation (AFS)** (`6_synchronisation.ipynb`): Run continuous, one-way background synchronisation of raw measurement folders from the openBIS Advanced File Server (AFS) to local AiiDAlab storage.
- **AI Agent**
  - **Open openBIS chatbot** (`4_openbis_chatbot.ipynb`): Interact with an AI assistant connected to your openBIS instance.
  - **Setup openBIS chatbot** (`5_setup_chatbot.ipynb`): Configure the LLM provider/model and Langfuse observability for tracking chatbot interactions.

### End-to-End Measurement Pipeline

When acquiring experimental measurements on an instrument computer and processing them through AiiDAlab into openBIS, the tools work together as follows:

1. **Sample Preparation (`aiidalab-openbis`):** Create the sample and register its preparation steps in openBIS.
2. **Instrument Upload (`openbis-drive`):** On the instrument PC, `openbis-drive` watches the microscope output folder and uploads raw files directly to the openBIS server's **Advanced File Server (AFS)**.
3. **AFS Synchronisation (`aiidalab-openbis` → *Folder synchronisation (AFS)*):** A background worker in AiiDAlab continuously mirrors the raw files from openBIS AFS into a local AiiDAlab directory.
4. **Measurement Upload (`aiidalab-openbis` → *Sample measurement*):** A background watchdog monitors that local AiiDAlab directory, parses newly arrived measurement files (extracting metadata and generating image previews), and uploads the structured datasets into an openBIS **Measurement Session** linked to your Project, Experiment, Sample, and Instrument.

---

## 2. Prerequisites & Initial Setup

### 2.1 Obtaining a Personal Access Token (PAT) in openBIS
Before connecting AiiDAlab or `openbis-drive` to openBIS, retrieve your **Personal Access Token (PAT)** from the openBIS admin or user interface. Make sure the token is active and has not expired.

### 2.2 Configuring the ELN Connection in AiiDAlab
All modules in `aiidalab-openbis` authenticate using the AiiDAlab ELN configuration.

1. Open the **AiiDAlab** starting page.
2. Click on **Configure ELN** (inside `aiidalab_widgets_base`).
3. Select **openBIS** as the ELN type.
4. Enter the **openBIS Server URL**: `https://openbis-empa-lab205.ethz.ch` (the port `:443` is not needed here).
5. Paste your **Personal Access Token (PAT)** and save/connect the configuration as the default ELN.
6. From the **AiiDAlab** starting page, launch the **AiiDAlab-openBIS** app:
   - If the connection succeeds, you will see **Connected to openBIS!** in green at the top of the home page and all **Experiments** links will be enabled.
   - If the connection is missing or the token has expired, you will see a red warning (*"Please connect to openBIS using the Configure ELN in AiiDAlab starting page!"*) and the app links will remain disabled until you update the connection.

### 2.3 Setting Up `openbis-drive` (Instrument PC to openBIS AFS)
To automatically stream raw measurement files from the acquisition computer to openBIS AFS:

1. Download and install **openbis-drive** for Windows from: https://polybox.ethz.ch/index.php/s/PeS2yfGwxNDTcW2?openfile=true
2. Open the **openbis-drive** application on the instrument computer.
3. Click on **Synchronization tasks**.
4. Click **+ Add** to create a new synchronization job.
5. **Personal access token:** Paste your user Personal Access Token (PAT) obtained from the openBIS admin interface.
6. **openBIS server URL:** Fill in `https://openbis-empa-lab205.ethz.ch:443`.
7. **openBIS entity ID:** Enter or search for the entity ID (PermID) of the openBIS object where you want to send the files. It is recommended to select the **measurement instrument** as the object to receive the measurement files.
8. **openBIS server directory:** Search for and select the remote openBIS server directory where the files should be stored.
   - *Recommendation:* Create a directory hierarchy on openBIS that mirrors the folder structure inside your `K:` drive. To do this, open the measurement instrument object in openBIS, select the **Files** tab inside the object, and create the folders in a mirror way to what is inside the `K:` drive. Then search for and select that target directory here.
9. **Local directory:** Search for and select the local folder on the instrument computer where the measurement files are located.
   - *Recommendation:* Select the folder containing your measurements, such as the folder inside the `K:` drive with your username.
10. **Synchronization mode:** Select **Upload**.
11. Check **Enabled**.
12. **Advanced settings (Ignored files):**
    - Click on **Specific list of ignored files** and click **Copy global default**.
    - Add any additional file patterns you want to exclude. For example, to ignore all `.txt` files, add `*.txt` to the list.
13. Click **Apply** to start the synchronization job.

---

## 3. Sample Preparation (`1_sample_preparation.ipynb`)

From the home page (`0_home.ipynb`), open the **Experiments** tab and click **Sample preparation**. The interface is divided into three tabs corresponding to the stages of sample preparation.

### 3.1 Tab 1: Create new sample
Before recording any preparation steps, you must register your physical starting sample in openBIS.

1. **Select material:**
   - Open the **Select material type...** dropdown and choose the starting material category (e.g., crystal, slab, substrate).
   - Once a material type is selected, a **Select material...** dropdown appears along with **Sort by** checkboxes (**Name**, **Registration date**).
   - Select the specific material piece from the dropdown. A summary panel below will display all properties and parent links of that material.
2. **Sample name:**
   - Selecting a material automatically populates the **Sample name** field with `<YYYY-MM-DDTHH:MM:SS>_<MaterialName>`.
   - You may edit this name before saving (or rename the sample later in the *Register preparation* or *Sample measurement* interfaces).
3. **Save (💾):**
   - Click the **Save (💾)** button to create the sample in openBIS with status `ACTIVE`.
   - The newly created sample is immediately available in the **Register preparation** tab.

> **⚠️ Important Rule Regarding Materials:**
> If you create a new sample using a material piece that already has an `ACTIVE` sample in openBIS (either directly or through previous preparation steps), the older sample is automatically set to **Inactive / Disposed (`DISPOSED`)**. This reflects physical reality: when starting fresh with the same physical piece of material, its previous tracked preparation state no longer exists. If an error occurs while saving, all changes are automatically rolled back.

### 3.2 Tab 2: Register preparation
Use this tab to log the preparation workflow performed on an active sample.

#### Core Workflow Concepts
- **Process steps** happen **sequentially** (one after another).
- **Actions** within a single process step happen **simultaneously** (in parallel at the same time).
- **Observables** are real-time **datasets/observations** attached to a specific process step.

#### Step-by-Step Instructions
1. **Select project:**
   - Choose the target project from the **Project** dropdown.
   - Use **Sort by** (**Name**, **Registration Date**) or **Filter** (**My Projects Only**) to narrow down the list.
   - *Note:* If the required project does not exist yet, register it in the openBIS web interface first.
2. **Select experiment:**
   - Choose the experiment (within the selected project) where the preparation will be stored. You can sort by **Name** / **Registration Date** or filter by **My Experiments Only**.
   - **Create a new experiment (`+`):** If the experiment does not exist yet:
     1. Ensure a **Project** is selected above.
     2. Click the **`+`** button next to the **Experiment** dropdown.
     3. Enter the experiment **Name** and **Description**.
     4. Click **Save (💾)** (or **Cancel (✖)** to close without saving). The new experiment is created and selected automatically.
3. **Select sample:**
   - Choose your sample from the **Sample** dropdown (supports sorting by **Name** / **Registration Date** and filtering by **My Samples Only**).
   - **Auto-fill behavior:** If the selected sample already has previous process steps recorded in openBIS, the **Project** and **Experiment** dropdowns automatically update to match its most recent process step.
   - **Rename a sample (✏️):** To rename the selected sample, click the **Edit (✏️)** button next to the dropdown, type the **New Name**, and click **Save (💾)**.
4. **Inspect Sample history:**
   - Once a sample is selected, the **Sample history** panel automatically loads and displays all previously registered process steps, actions, and observables for that sample.
5. **Register new steps:**
   You can populate the **Register new steps** accordion either by loading a saved template or by building steps from scratch:
   - **Option A — Load a process template (`Load process`):**
     1. Click the **Load process** button.
     2. Select a saved recipe from the **Select a process...** dropdown (or click **X** to cancel).
     3. All sequential steps and actions from the template are loaded into the accordion. You can then review/edit parameters, select rooms/instruments, or attach observables.
   - **Option B — Build steps manually (`Add process step`):**
     1. Click **Add process step** to add a new step to the accordion.
     2. Fill in the step's **Name**, **Description**, and **Comments**.
     3. Select the **Room** where the step is performed. This enables the **Instrument** dropdown and filters it to instruments located in that room (plus *Other Tools* for unattached components in that room).
     4. Select the **Instrument**.
     5. **Add Actions (`+ Add action`):**
        - Click **Add action** inside the step.
        - Select an **Action type** supported by the chosen instrument.
        - Fill in the action parameters (e.g., duration, comments, used substances/materials, target substrate/stamp, and specific **Components** along with their **Component Settings**).
        - Repeat **Add action** for any actions occurring simultaneously during the same step, or click **Remove (🗑️)** inside an action to delete it.
     6. **Add Observables (`+ Add observable`):**
        - Click **Add observable** to attach real-time observable data/properties to the process step, or click **Remove (🗑️)** to delete an observable.
     7. To remove an entire process step, click **Remove (🗑️)** at the bottom of that step's panel.
6. **Save (💾):**
   - Click the **Save (💾)** button at the bottom of the page to register the preparation and all new steps, actions, component settings, and observables in openBIS.
   - If an error occurs during any part of the save operation, all newly created openBIS objects from that submission are automatically rolled back.

### 3.3 Tab 3: Save process template
Use this tab to create reusable **Templates** (recipes) for multi-step processes you perform frequently (for example, a standard sputtering-annealing sequence), so you do not need to rebuild them from scratch each time.

1. **Select collection:** Choose the openBIS collection where the process template will be saved.
2. **Process properties:**
   - **Name:** Full descriptive name of the process template.
   - **Short name:** A short abbreviation (e.g., `SPAN` for Sputtering-Annealing).
   - **Description:** Notes describing what this recipe does.
3. **Register new steps:**
   - Click **Add process step** to build the sequence of steps and attach simultaneous **Actions** (with their Room, Instrument, Components, and Component Settings), just like in the *Register preparation* tab.
   - *Note:* **Observables** are not available when saving a process template because observables are only generated during real-time execution on a physical sample.
4. **Save (💾):**
   - Click **Save (💾)** to store the blueprint in openBIS. It will immediately become available under **Load process** in the *Register preparation* tab.

---

## 4. Folder Synchronisation — AFS (`6_synchronisation.ipynb`)

From the home page (`0_home.ipynb`), open the **Experiments** tab and click **Folder synchronisation (AFS)**.

This module establishes automated, continuous, one-way background synchronisation from the **openBIS Advanced File Server (AFS)** to local AiiDAlab storage. New files, modifications, and deletions on openBIS AFS are mirrored locally, while unchanged files are not re-downloaded.

### 4.1 Tab 1: Setup Synchronisation
1. **1. Select openBIS Object:**
   - Enter the target Object, Instrument, Sample, or Experiment **Identifier** (e.g., `/DEFAULT/RAW_EXP/SAMPLE_1`) or **PermID** in the text box.
   - Click **Search & Browse AFS**.
   - Once found, the interface loads all available remote directories into the **AFS Folder** dropdown and pre-fills a default local path (`/home/jovyan/data/openbis_raw_scans/<object_code>`).
2. **2. Source Folder in AFS:**
   - Select the remote folder on the AFS server that you want to synchronize from the **AFS Folder** dropdown (`/` synchronizes the entire object root).
3. **3. Destination Folder in AiiDAlab:**
   - Type the local destination path in **Local Path**, or click **Browse Folder** to open the interactive directory browser, select a directory, and confirm.
4. **4. Synchronisation Frequency:**
   - Choose how often the background worker checks AFS for changes using the **Poll Interval** dropdown (`5 seconds`, `10 seconds`, `30 seconds`, `1 minute`, `5 minutes`, `15 minutes`, `30 minutes`, or `1 hour`; defaults to `1 minute`).
5. **Conflict Detection:**
   - If the selected AFS source or local destination folder is already being synchronized by an active job, a red **⚠️ Synchronisation Conflict Detected** warning banner appears and disables the start button. Manage or stop the existing job in the *Active Synchronisations* tab first.
6. **Start Background Synchronisation:**
   - Click **Start Background Synchronisation (▶️)**.
   - A detached background worker process is launched, and the interface automatically switches to the **Active Synchronisations** tab.

### 4.2 Tab 2: Active Synchronisations
This tab displays status cards for all configured synchronisation jobs and automatically resumes any `RUNNING` jobs that were interrupted by a system/container restart.

- **Refresh Status:** Click **Refresh Status (🔄)** to update job statuses, download progress, and synced file counts.
- **Managing Running Jobs (`● RUNNING`):**
  - Click **Stop Sync (⏹️)** on a running job card to pause/stop it. You will be prompted with three options:
    - **Stop & Delete Local Data (🗑️):** Stops the background worker and deletes the downloaded files in the local target folder to free disk space.
    - **Stop & Keep Data (⏸️):** Stops the background worker and keeps all downloaded files on disk.
    - **Cancel:** Cancels the prompt and keeps the synchronisation running.
- **Managing Stopped Jobs (`○ STOPPED`):**
  - **Resume Sync (▶️):** Restarts the background synchronisation worker (provided no conflicting job is using the same paths).
  - **Dismiss (✖):** Removes the job card from the list. If downloaded files still exist in the local folder, you will be asked whether to **Dismiss & Delete Data (🗑️)**, **Dismiss & Keep Data**, or **Cancel**.

---

## 5. Sample Measurement Uploader (`2_sample_measurement.ipynb`)

From the home page (`0_home.ipynb`), open the **Experiments** tab and click **Sample measurement**.

The **Measurement Uploader** launches background **Watchdogs** that monitor local AiiDAlab directories (such as a folder actively populated by **AFS Synchronisation**) and automatically parse and upload measurement files into an openBIS **Measurement Session** linked to your Experiment, Sample, and Instrument.

### 5.1 Tab 1: Start directory monitoring
1. **Select project:**
   - Choose the openBIS project from the **Project** dropdown (sortable by **Name** / **Registration Date**, filterable by **My Projects Only**).
2. **Select experiment:**
   - Choose the target experiment within the selected project (sortable by **Name** / **Registration Date**, filterable by **My Experiments Only**).
   - **Create a new experiment (`+`):** If the experiment does not exist yet, select a Project first, click the **`+`** button next to the Experiment dropdown, enter the **Name** and **Description**, and click **Save (💾)**.
3. **Select sample:**
   - Choose the sample being measured from the **Sample** dropdown (supports sorting, **My Samples Only** filter, and renaming via the **Edit ✏️** button).
   - **Auto-fill behavior:** When you select a sample:
     - The **Measurement session details → Name** field automatically populates as `MEAS_<SampleName>`.
     - If the sample has a registered **Process Step**, the **Project** and **Experiment** dropdowns automatically update to match the experiment of its most recent process step.
4. **Select instrument:**
   - Choose the measurement device from the **Instrument** dropdown (sortable by **Name** or **Registration date**).
5. **Measurement session details:**
   - Review or edit the **Name** of the Measurement Session.
6. **Select measurements directory:**
   - Use the folder chooser to select the local directory where measurement files appear (for example, the local target folder configured in **Folder synchronisation (AFS)**).
   - **Important:** After navigating to the desired folder in the chooser, click **Change** to confirm the path selection. If the folder chooser is left in edit mode (showing *Cancel*), saving will be blocked with an alert.
7. **Save (💾):**
   - Click the **Save (💾)** button to start the watchdog:
     - **Session Creation / Reuse:** If a valid openBIS **Measurement Session** was previously created for that exact folder, the uploader reuses it; otherwise, it creates a new **Measurement Session** in openBIS linked to the selected Experiment, Sample, and Instrument.
     - **Duplicate Check:** If the directory is already being monitored by an active watchdog, an alert notifies you and prevents starting a duplicate process.
     - **File Processing:** The background watchdog immediately processes any existing unuploaded files in the folder and continuously monitors for new or moved files. It waits until each file finishes writing, parses Nanonis measurement files, uploads datasets to openBIS, and tracks processed files so they are never uploaded twice. Hidden files (starting with `.`) and temporary/metadata files ending in `.json`, `.ini`, `.part`, `.openbis-drive-part`, or `.tmp` are automatically ignored.

### 5.2 Tab 2: Directories being monitored
Use this tab to inspect and stop running measurement watchdogs.

1. **Running watchdogs:**
   - Displays all directory paths currently being monitored by active background watchdog processes (any processes that have already exited are automatically pruned when the list refreshes).
2. **Stop monitoring (🚫):**
   - Select one or more directories from the **Running watchdogs** list.
   - Click the **Stop watchdog (🚫)** button to terminate the corresponding background process(es) and remove them from the active monitoring list.

---

## 6. Navigation

- **Return to Main Menu (🏠):** Click the **Home (🏠)** button at the bottom of any notebook to return to the main page (`0_home.ipynb`).
