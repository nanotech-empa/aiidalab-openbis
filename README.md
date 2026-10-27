# D2.1 - Metadata schema to store and access microscopy data

> **Legacy Python 3.9 / AiiDA 2.6.3:** use [v0.1.1](https://github.com/nanotech-empa/aiidalab-openbis/releases/tag/v0.1.1). See the [Empa legacy compatibility guide](https://github.com/nanotech-empa/aiida-nanotech-empa/blob/master/docs/legacy-python39-aiida263.md) for the matching package versions and installation constraints. Use a tagged version to preserve this runtime.

Common metadata schema to store and access microscopy data from simulations and experiments in a single platform.

## Authors
- Aliaksandr Yakutovich
- Fabio Lopes
- Carlo Pignedoli

## Goal
* `home.ipynb` is the main page for the whole AiiDAlab-openBIS interface.
* `import_export_simulations.ipynb` is the interface to import and export simulations from/to openBIS.
* `openbis_chatbot.ipynb` is the interface to interact with the openBIS chatbot.
* `sample_measurement.ipynb` is the interface to start measurement uploader watchdogs.
* `sample_preparation.ipynb` is the interface to create samples, register preparations, and register template processes.
* `upload_substances.ipynb` is the interface to upload the information about new substances into openBIS.
* `create_analysis.ipynb` uploads the information about data analysis into openBIS.
* `create_results.ipynb` uploads the information about results into openBIS.
* `create_drafts.ipynb` uploads the information about publication drafts into openBIS.
* `src` contains tools necessary to run the interfaces.
* `schema` contains schema-related files based on [Pydantic](https://docs.pydantic.dev/latest/) classes.
* `ai_agent` contains agentic AI tools.
* `data` contains some examples of SPM measurements.
* `deprecated` contains deprecated files that are to be removed.
* `logs` contains log files.
* `metadata` contains metadata files needed for the interfaces.
* `nanonis_importer` contains NANONIS importer files.
* `tests` contains some test notebooks.

## Achievement
This repository contains all the files needed for setting up and interact with the openBIS instance.

## External links
- https://www.ebi.ac.uk/ols4/
- https://linkml.io/

## Acknowledgements
The [PREMISE](https://ord-premise.github.io/) project is supported by the [Open Research Data Program](https://ethrat.ch/en/eth-domain/open-research-data/) of the ETH Board.

![image](https://github.com/ord-premise/metadata-batteries/assets/45081142/74640b5c-ee94-41e1-9acd-fa47da866fe8)
