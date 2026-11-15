"""Shared chat pilot alongside Fabio's original chatbot."""


def create_panel():
    import os

    import ipywidgets as ipw

    legacy = ipw.HTML(
        '<p><a href="4_openbis_chatbot_legacy.ipynb" target="_blank">Open Fabio’s original chatbot</a></p>'
    )
    if os.environ.get("AIIDALAB_OPENBIS_CHAT", "shared") == "legacy":
        return ipw.VBox(
            [ipw.HTML("The original chatbot is selected for this instance."), legacy]
        )
    try:
        from aiidalab_ai_assistant import AssistantPanel
        from aiidalab_ai_assistant.forms import FormAdapter
    except ModuleNotFoundError as exc:
        if exc.name not in {"aiidalab_ai_assistant", "aiidalab_ai_assistant.forms"}:
            raise
        return ipw.VBox(
            [
                ipw.HTML(
                    "Install the optional aiidalab-ai-assistant package to use the shared chat."
                ),
                legacy,
            ]
        )
    adapter = FormAdapter(
        "aiidalab-openbis",
        lambda: {},
        context=lambda: {
            "workspace": "openBIS search and workflow guidance",
            "changes": "Use the existing import/export and preparation GUIs.",
            "migration": "Typed material and relationship searches are available. Legacy document-vector retrieval and automatic archive import have not migrated.",
        },
    )
    return ipw.VBox(
        [
            ipw.HTML(
                "<h2>openBIS assistant</h2><p>Search laboratory records and follow simulation and sample provenance.</p>"
            ),
            AssistantPanel(adapter=adapter),
            legacy,
        ]
    )
