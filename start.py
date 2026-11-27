import ipywidgets as ipw


def get_start_widget(appbase, jupbase, notebase):
    logo_src = notebase.replace("/notebooks/", "/files/", 1) + "/aiidalab_openbis_logo.png"
    return ipw.HTML(
        f"""
    <div align="center">
        <a href="{appbase}/0_home.ipynb" target="_blank">
                <img src="{logo_src}" alt="nanotech@openbis" height="120px" width="243px">
        </a>
    </div>"""
    )
