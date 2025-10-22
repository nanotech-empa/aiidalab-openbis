import ipywidgets as ipw


def get_start_widget(appbase, jupbase, notebase):
    return ipw.HTML(
        f"""
    <div align="center">
        <a href="{appbase}/home.ipynb" target="_blank">
                <img src="https://github.com/nanotech-empa/aiidalab-openbis/blob/prepare-interface-to-install/aiidalab_openbis_logo.jpg?raw=true" height="120px" width="243px">
        </a>
    </div>"""
    )
