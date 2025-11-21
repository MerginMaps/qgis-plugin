# GPLv3 license
# Copyright Lutra Consulting Limited

HELP_ROOT = "https://merginmaps.com/docs"


class MerginHelp:
    """Class for generating Mergin plugin help URLs."""

    def howto_attachment_widget(self):
        return f"{HELP_ROOT}/layer/settingup_forms/"

    def howto_background_maps(self):
        return f"{HELP_ROOT}/gis/settingup_background_map/"

    def howto_photo_attachment(self):
        return f"{HELP_ROOT}/layer/photos/#photo-attachment-widget-in-qgis"
