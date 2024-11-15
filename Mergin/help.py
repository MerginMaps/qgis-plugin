MAIN_ROOT = "https://merginmaps.com/"

class MerginHelp:
    """Class for generating Mergin plugin help URLs."""

    def howto_attachment_widget(self):
        return f"{MAIN_ROOT}/docs/layer/settingup_forms/"

    def howto_background_maps(self):
        return f"{MAIN_ROOT}/docs/gis/settingup_background_map/"
    
    def mergin_subscription_link(self):
        return f"{MAIN_ROOT}/pricing/"
