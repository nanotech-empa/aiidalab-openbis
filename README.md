# D2.1 - Metadata schema to store and access microscopy data
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

## Software attribution and scientific acknowledgements

Please credit [aiidalab-openbis](https://github.com/nanotech-empa/aiidalab-openbis) and its
[contributors](https://github.com/nanotech-empa/aiidalab-openbis/graphs/contributors),
and identify the release or immutable commit used. Existing author,
contributor and funding acknowledgements remain authoritative.

Package metadata declares MIT, but this revision has no top-level licence
file. Confirm the applicable notices with the maintainers before copying
or distributing code; this citation guidance does not supply a licence.

For research using this app, acknowledge the [AiiDA team](https://github.com/nanotech-empa/.github/blob/main/CITATION_GUIDANCE.md#aiida)
and [AiiDAlab team](https://github.com/nanotech-empa/.github/blob/main/CITATION_GUIDANCE.md#aiidalab), and cite the three AiiDA papers
and both AiiDAlab platform papers listed in that guide.

Preserve the Authors and PREMISE acknowledgements above. Also credit openBIS, pyBIS and the ELN integrations actually used.

The [shared credit guide](https://github.com/nanotech-empa/.github/blob/main/CITATION_GUIDANCE.md) keeps software attribution, licence
compliance and scientific citation requests separate. Scientific citation
requests are not additional MIT licence conditions.
