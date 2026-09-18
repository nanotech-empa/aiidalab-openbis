# D2.1 - Metadata schema to store and access microscopy data
Common metadata schema to store and access microscopy data from simulations and experiments in a single platform.

## Supported runtime

This integrated version requires **Python >=3.12** and **AiiDA >=2.8,<3**.
Python 3.9–3.11 and AiiDA versions below 2.8 are no longer supported or tested.
The previous branch-specific backwards-compatibility window is closed here.
The AiiDA 3 upper bound is retained from the existing requirements.

The integrated runtime has been exercised with Python 3.12.11, AiiDA 2.8.0,
AiiDAlab 26.5.2 and ipywidgets 8.1.8. Other dependency pins are unchanged;
the packaging branch's `aiidalab-eln>=0.1.4` requirement is included.
This support floor is a maintainer policy, not a claim that every older
combination necessarily fails or every future version has been tested.

See [integration notes](docs/runtime_integration.md) for the source branches,
validation scope and remaining production checks.

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
